import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { renderApp } from "../test/render";
import { DEMO_BANNER } from "../session/signInOptions";

describe("the demo banner", () => {
  it("shows on the sign-in page when the demo is on", async () => {
    await renderApp("/sign-in");
    expect(await screen.findByText(DEMO_BANNER)).toBeVisible();
  });

  it("stays on a signed-in page, outside the header", async () => {
    await renderApp("/sign-in");
    await userEvent.click(
      await screen.findByRole("button", { name: "Staff nurse · Sarah Navarro, RN" }),
    );
    await screen.findByRole("heading", { name: "Patients on this ward" });
    const banner = screen.getByText(DEMO_BANNER);
    expect(banner).toBeVisible();
    expect(screen.getByRole("banner")).not.toContainElement(banner);
  });

  it("shows on the not-found screen", async () => {
    await renderApp("/nowhere");
    expect(await screen.findByText(DEMO_BANNER)).toBeVisible();
  });

  it("is absent when the demo is off", async () => {
    await renderApp("/sign-in", { demo: false });
    await screen.findByRole("button", { name: "Staff nurse · Sarah Navarro, RN" });
    expect(screen.queryByText(DEMO_BANNER)).not.toBeInTheDocument();
  });
});
