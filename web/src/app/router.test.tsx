import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/errors";
import { sessionKey } from "../session/session";
import { server } from "../test/setup";
import { PendingScreen } from "./RouteScreens";
import { renderApp } from "../test/render";

// Silences console.warn and console.error for one test and gives back the calls, so a test can
// assert that every call was an expected one. Restore both spies in a finally.
function spyOnConsole() {
  const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
  const error = vi.spyOn(console, "error").mockImplementation(() => undefined);
  return {
    warn,
    error,
    restore: () => {
      warn.mockRestore();
      error.mockRestore();
    },
  };
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
    const spy = spyOnConsole();
    try {
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
      expect(spy.warn).toHaveBeenCalled();
      for (const call of spy.warn.mock.calls) {
        expect(call[0]).toBe("Warning: Error in route match: /app/");
      }
      expect(spy.error).toHaveBeenCalled();
      for (const call of spy.error.mock.calls) {
        expect(call.some((arg) => arg instanceof ApiError)).toBe(true);
      }
    } finally {
      spy.restore();
    }
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

  it("has a loading screen with words for a screen reader", () => {
    render(<PendingScreen />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });
});
