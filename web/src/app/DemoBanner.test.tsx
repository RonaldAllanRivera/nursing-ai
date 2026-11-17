import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
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

  it("asks the options again after one failure, then shows both the banner and the Google link", async () => {
    let failures = 1;
    await renderApp("/sign-in", { google: true }, [
      http.get("*/api/v1/sign-in-options", () => {
        if (failures-- > 0) return HttpResponse.json({}, { status: 503 });
        return undefined;
      }),
    ]);
    expect(await screen.findByText(DEMO_BANNER, {}, { timeout: 4000 })).toBeVisible();
    expect(screen.getByRole("link", { name: "Sign in with Google" })).toBeVisible();
  });

  it("is absent when the demo is off", async () => {
    await renderApp("/sign-in", { demo: false });
    await screen.findByRole("button", { name: "Staff nurse · Sarah Navarro, RN" });
    expect(screen.queryByText(DEMO_BANNER)).not.toBeInTheDocument();
  });
});
