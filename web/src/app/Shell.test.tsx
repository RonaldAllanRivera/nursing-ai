import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { renderApp } from "../test/render";
import { server } from "../test/setup";

afterEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

async function signInAs(name: string) {
  const view = await renderApp("/sign-in");
  await userEvent.click(await screen.findByRole("button", { name }));
  return view;
}

describe("shell and guards", () => {
  it("sends you to sign-in when not signed in", async () => {
    await renderApp("/patients");
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeVisible();
  });

  it("sends / to sign-in when not signed in", async () => {
    await renderApp("/");
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeVisible();
  });

  it("changing the shift updates the header", async () => {
    await signInAs("Staff nurse · Sarah Navarro, RN");
    const header = await screen.findByRole("banner");
    expect(await within(header).findByText("Shift 10-6")).toBeVisible();
    await userEvent.click(within(header).getByRole("button", { name: "Change shift" }));
    const choice = await screen.findByRole("button", { name: /^2-10/ });
    expect(choice).toHaveAccessibleName("2-10 14:00 to 22:00 11 Nov 2026");
    await userEvent.click(choice);
    expect(await within(header).findByText("Shift 2-10")).toBeVisible();
    expect(within(header).queryByText("Shift 10-6")).toBeNull();
  });

  it("shows the admin's role chip and only Settings", async () => {
    await signInAs("Admin · Victor Lazaro");
    const header = await screen.findByRole("banner");
    expect(within(header).getByText("Victor Lazaro")).toBeVisible();
    expect(within(header).getByText("Admin")).toBeVisible();
    expect(within(header).getByRole("link", { name: "Settings" })).toBeVisible();
    expect(within(header).queryByRole("link", { name: "Patients" })).toBeNull();
    expect(within(header).queryByRole("button", { name: "Change shift" })).toBeNull();
  });

  it("shows a nurse's role chip, a Patients link and no Settings", async () => {
    await signInAs("Head nurse · Grace Villareal, RN");
    const header = await screen.findByRole("banner");
    expect(within(header).getByText("Head nurse")).toBeVisible();
    expect(within(header).getByRole("link", { name: "Patients" })).toBeVisible();
    expect(within(header).queryByRole("link", { name: "Settings" })).toBeNull();
  });

  it("keeps a nurse off /settings and the admin off /patients", async () => {
    const nurse = await signInAs("Staff nurse · Sarah Navarro, RN");
    await screen.findByRole("heading", { name: "Patients on this ward" });
    await nurse.router.navigate({ to: "/settings" });
    expect(await screen.findByRole("heading", { name: "Patients on this ward" })).toBeVisible();
    nurse.unmount();

    const admin = await signInAs("Admin · Victor Lazaro");
    await screen.findByRole("heading", { name: "Settings" });
    await admin.router.navigate({ to: "/patients" });
    expect(await screen.findByRole("heading", { name: "Settings" })).toBeVisible();
  });

  it("signs out and returns to sign-in", async () => {
    await signInAs("Staff nurse · Sarah Navarro, RN");
    await userEvent.click(await screen.findByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeVisible();
  });

  it("toggles the night theme on <html> and remembers it", async () => {
    await signInAs("Staff nurse · Sarah Navarro, RN");
    const toggle = await screen.findByRole("button", { name: "Night theme" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(document.documentElement.dataset["theme"]).toBe("night");
    expect(localStorage.getItem("theme")).toBe("night");
    await userEvent.click(toggle);
    expect(document.documentElement.dataset["theme"]).toBe("day");
  });

  it("keeps the admin off a patient's page too", async () => {
    const admin = await signInAs("Admin · Victor Lazaro");
    await screen.findByRole("heading", { name: "Settings" });
    await admin.router.navigate({ to: "/patients/$patientId", params: { patientId: "abc" } });
    expect(await screen.findByRole("heading", { name: "Settings" })).toBeVisible();
    expect(admin.router.state.location.pathname).toBe("/settings");
  });

  it("says so when the facility's shifts do not load, and Try again fetches them", async () => {
    await renderApp("/sign-in");
    let down = true;
    server.use(
      http.get("*/api/v1/facilities/:key", () =>
        down ? HttpResponse.json({}, { status: 500 }) : undefined,
      ),
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Staff nurse · Sarah Navarro, RN" }),
    );
    await userEvent.click(await screen.findByRole("button", { name: "Change shift" }));
    const group = within(await screen.findByRole("group", { name: "Shifts you can work" }));
    expect(await group.findByText("The shifts did not load.")).toBeVisible();
    down = false;
    await userEvent.click(group.getByRole("button", { name: "Try again" }));
    expect(await group.findByRole("button", { name: /^2-10/ })).toBeVisible();
    expect(group.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("after Try again works, focus lands on the current shift's button", async () => {
    await renderApp("/sign-in");
    let down = true;
    server.use(
      http.get("*/api/v1/facilities/:key", () =>
        down ? HttpResponse.json({}, { status: 500 }) : undefined,
      ),
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Staff nurse · Sarah Navarro, RN" }),
    );
    await userEvent.click(await screen.findByRole("button", { name: "Change shift" }));
    const group = within(await screen.findByRole("group", { name: "Shifts you can work" }));
    await group.findByText("The shifts did not load.");
    down = false;
    await userEvent.click(group.getByRole("button", { name: "Try again" }));
    const current = await waitFor(() => {
      const found = group.getByRole("button", { pressed: true });
      return found;
    });
    await waitFor(() => {
      expect(current).toHaveFocus();
    });
  });

  it("announces again when Try again fails again", async () => {
    await renderApp("/sign-in");
    server.use(http.get("*/api/v1/facilities/:key", () => HttpResponse.json({}, { status: 500 })));
    await userEvent.click(
      await screen.findByRole("button", { name: "Staff nurse · Sarah Navarro, RN" }),
    );
    await userEvent.click(await screen.findByRole("button", { name: "Change shift" }));
    const group = within(await screen.findByRole("group", { name: "Shifts you can work" }));
    const first = await group.findByRole("alert");
    expect(first).toHaveTextContent("The shifts did not load.");
    await userEvent.click(group.getByRole("button", { name: "Try again" }));
    await waitFor(() => {
      expect(first).not.toBeInTheDocument();
    });
    const second = await group.findByRole("alert");
    expect(second).not.toBe(first);
    expect(second).toHaveTextContent("The shifts did not load.");
  });

  it("opening the shifts the first time leaves focus on the change button", async () => {
    await signInAs("Staff nurse · Sarah Navarro, RN");
    const toggle = await screen.findByRole("button", { name: "Change shift" });
    await userEvent.click(toggle);
    const group = within(await screen.findByRole("group", { name: "Shifts you can work" }));
    expect(await group.findByRole("button", { name: /^2-10/ })).toBeVisible();
    expect(toggle).toHaveFocus();
  });

  it("keeps the shifts on screen when a refresh of the facility fails", async () => {
    const { queryClient } = await signInAs("Staff nurse · Sarah Navarro, RN");
    await userEvent.click(await screen.findByRole("button", { name: "Change shift" }));
    const group = within(await screen.findByRole("group", { name: "Shifts you can work" }));
    expect(await group.findByRole("button", { name: /^2-10/ })).toBeVisible();
    server.use(http.get("*/api/v1/facilities/:key", () => HttpResponse.json({}, { status: 500 })));
    await queryClient.invalidateQueries({ queryKey: ["facility"] });
    await act(() => new Promise((resolve) => setTimeout(resolve, 20)));
    expect(group.getByRole("button", { name: /^2-10/ })).toBeVisible();
    expect(group.queryByRole("alert")).not.toBeInTheDocument();
  });
});
