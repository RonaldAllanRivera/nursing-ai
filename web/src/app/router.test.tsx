import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, onTestFinished, vi } from "vitest";
import { sessionKey } from "../session/session";
import { server } from "../test/setup";
import { PendingScreen, ShellFrame } from "./RouteScreens";
import { renderApp } from "../test/render";

// A patient page that throws on render while `pageBreaks.on` is set, to show a child page failing.
const pageBreaks = vi.hoisted(() => ({ on: false }));
vi.mock("../patients/PatientPage", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../patients/PatientPage")>();
  return {
    ...actual,
    PatientPage: () => {
      if (pageBreaks.on) throw new Error("synthetic page failure");
      return <actual.PatientPage />;
    },
  };
});

const AID_LINE = "Documentation aid — the nurse reviews and signs every note.";

// Silences console.warn and console.error for the rest of one test. When the test is over (after
// the cleanup and handler reset, so their calls count too) it checks there was at least one call
// of each kind and that every call carries the expected argument (the received arguments are
// printed when one does not), then always restores both.
function spyOnConsole(expected: { warn: unknown; error: unknown }) {
  const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
  const error = vi.spyOn(console, "error").mockImplementation(() => undefined);
  onTestFinished(() => {
    try {
      for (const [spy, arg] of [
        [warn, expected.warn],
        [error, expected.error],
      ] as const) {
        expect(spy.mock.calls.length).toBeGreaterThan(0);
        for (const call of spy.mock.calls) {
          expect(call).toContainEqual(arg);
        }
      }
    } finally {
      warn.mockRestore();
      error.mockRestore();
    }
  });
}

async function signInAsNurse() {
  const app = await renderApp("/sign-in");
  await userEvent.click(
    await screen.findByRole("button", { name: "Staff nurse · Sarah Navarro, RN" }),
  );
  await screen.findByRole("heading", { name: "Patients on this ward" });
  return app;
}

describe("app router", () => {
  it("shows the sign-in page with the health line and the aid line", async () => {
    await renderApp("/sign-in");
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeVisible();
    expect(
      screen.getByText("Documentation aid — the nurse reviews and signs every note."),
    ).toBeInTheDocument();
    expect(await screen.findByText("API: healthy")).toBeInTheDocument();
  });

  it("sends / on to the patients for a nurse", async () => {
    const { router } = await renderApp("/sign-in");
    await userEvent.click(
      await screen.findByRole("button", { name: "Staff nurse · Sarah Navarro, RN" }),
    );
    await screen.findByRole("heading", { name: "Patients on this ward" });
    await router.navigate({ to: "/" });
    expect(await screen.findByRole("heading", { name: "Patients on this ward" })).toBeVisible();
    expect(router.state.location.pathname).toBe("/patients");
  });

  it("sends you to sign-in when a request comes back 401 mid-session", async () => {
    const { queryClient } = await renderApp("/sign-in");
    await userEvent.click(
      await screen.findByRole("button", { name: "Staff nurse · Sarah Navarro, RN" }),
    );
    await screen.findByRole("heading", { name: "Patients on this ward" });
    await screen.findAllByRole("link", { name: /Demo patient/ });
    server.use(
      http.get("*/api/v1/patients", () =>
        HttpResponse.json(
          { type: "about:blank", title: "Not signed in", status: 401, code: "not_signed_in" },
          { status: 401, headers: { "Content-Type": "application/problem+json" } },
        ),
      ),
    );
    await queryClient.invalidateQueries({ queryKey: ["patients"] });
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeVisible();
  });

  it("loads the lazy Settings route for the admin, and sends nobody else there", async () => {
    const admin = await renderApp("/sign-in");
    await userEvent.click(await screen.findByRole("button", { name: "Admin · Victor Lazaro" }));
    expect(await screen.findByRole("heading", { name: "Settings" })).toBeVisible();
    expect(admin.router.state.location.pathname).toBe("/settings");
    expect(await screen.findByRole("textbox", { name: "Facility name" })).toBeVisible();
    admin.unmount();
    await renderApp("/settings");
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeVisible();
  });

  it("sends you to sign-in when a write comes back 401", async () => {
    await renderApp("/sign-in");
    await userEvent.click(
      await screen.findByRole("button", { name: "Staff nurse · Sarah Navarro, RN" }),
    );
    await userEvent.click(await screen.findByRole("button", { name: "Change shift" }));
    const choice = await screen.findByRole("button", { name: /^2-10/ });
    server.use(
      http.put("*/api/v1/session/shift", () =>
        HttpResponse.json(
          { type: "about:blank", title: "Not signed in", status: 401, code: "not_signed_in" },
          { status: 401, headers: { "Content-Type": "application/problem+json" } },
        ),
      ),
    );
    await userEvent.click(choice);
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeVisible();
  });

  it("shows a plain screen with Try again when the session does not load, and recovers", async () => {
    // The router warns and React reports the caught error for any route that errors; the screen is
    // what counts here, but every console call must be one we expect.
    spyOnConsole({
      warn: "Warning: Error in route match: /app/",
      error: expect.objectContaining({ name: "ApiError", status: 500 }),
    });
    const { router, queryClient } = await renderApp("/sign-in");
    await userEvent.click(
      await screen.findByRole("button", { name: "Staff nurse · Sarah Navarro, RN" }),
    );
    await screen.findByRole("heading", { name: "Patients on this ward" });
    let down = true;
    server.use(
      http.get("*/api/v1/session", () =>
        down ? HttpResponse.json({}, { status: 500 }) : undefined,
      ),
    );
    queryClient.removeQueries({ queryKey: sessionKey });
    await router.navigate({ to: "/patients" });
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Something went wrong loading this page.");
    expect(screen.queryByText(/Hide Error|Show Error|request failed/)).not.toBeInTheDocument();
    expect(
      screen.getByText("Documentation aid — the nurse reviews and signs every note."),
    ).toBeInTheDocument();
    down = false;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: "Patients on this ward" })).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows a plain not-found screen with a way back", async () => {
    await renderApp("/nope");
    expect(await screen.findByText("There's no page at this address.")).toBeVisible();
    expect(
      screen.getByText("Documentation aid — the nurse reviews and signs every note."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Not Found")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("link", { name: "Go to the start" }));
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeVisible();
  });

  it("shows one aid line and no nested main when a page inside the shell fails", async () => {
    spyOnConsole({
      warn: expect.stringContaining("Error in route match"),
      error: expect.objectContaining({ message: "synthetic page failure" }),
    });
    const { router } = await signInAsNurse();
    pageBreaks.on = true;
    onTestFinished(() => {
      pageBreaks.on = false;
    });
    await router.navigate({ to: "/patients/$patientId", params: { patientId: "abc" } });
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Something went wrong loading this page.",
    );
    expect(screen.getByRole("button", { name: "Try again" })).toBeVisible();
    expect(screen.getAllByText(AID_LINE)).toHaveLength(1);
    expect(document.querySelectorAll("main main")).toHaveLength(0);
  });

  it("shows one aid line and no nested main for an unknown address when signed in", async () => {
    const { router } = await signInAsNurse();
    router.history.push("/patients/abc/xyz");
    expect(await screen.findByText("There's no page at this address.")).toBeVisible();
    expect(screen.getAllByText(AID_LINE)).toHaveLength(1);
    expect(document.querySelectorAll("main main")).toHaveLength(0);
  });

  it("gives the not-found screen its own aid line and main when signed out", async () => {
    await renderApp("/nope");
    expect(await screen.findByText("There's no page at this address.")).toBeVisible();
    expect(screen.getAllByText(AID_LINE)).toHaveLength(1);
    expect(document.querySelectorAll("main")).toHaveLength(1);
  });

  it("shows the loading screen inside the shell without a second aid line or main", () => {
    render(
      <ShellFrame.Provider value={true}>
        <main>
          <PendingScreen />
        </main>
      </ShellFrame.Provider>,
    );
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(document.querySelector('[aria-busy="true"]')).not.toBeNull();
    expect(screen.queryByText(AID_LINE)).not.toBeInTheDocument();
    expect(document.querySelectorAll("main main")).toHaveLength(0);
  });

  it("has a loading screen with words for a screen reader", () => {
    render(<PendingScreen />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });
});
