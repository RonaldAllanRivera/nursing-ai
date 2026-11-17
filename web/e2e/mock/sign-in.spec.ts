// The sign-in screen with Google on, a refusal above it and the demo banner, then the header's
// shift picker, against the mock API at 375, 768 and 1280 px. The plain sign-in, the header and
// the patient list are the first steps of the PH flow in journeys.spec.ts.
import { expect, test } from "@playwright/test";
import {
  DEMO_BANNER_TEXT,
  SARAH,
  checkScreen,
  expectHeaderAtMostTwoRows,
  noSidewaysScroll,
  setMockOptions,
  shot,
  signInAsSarah,
  tabTo,
} from "./helpers.ts";

test("sign-in with Google on: refusal, Google link first, personas and PIN, by keyboard", async ({
  page,
}) => {
  await setMockOptions(page, { google: true });
  await page.goto("/sign-in?error=no_access");

  await expect(page.getByRole("alert")).toHaveText(
    "You don't have access yet. Ask the admin to invite your Google account.",
  );
  await expect(page.getByText(DEMO_BANNER_TEXT)).toBeVisible();
  await expect(page.getByText("Demo PIN: 135790")).toBeVisible();
  await checkScreen(page);
  await shot(page, "sign-in-google");

  // Keyboard only: the Google link comes first, then the first person.
  const google = page.getByRole("link", { name: "Sign in with Google" });
  await expect(google).toHaveAttribute("href", "/api/v1/auth/google/start");
  await tabTo(page, google);
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: SARAH })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Patients on this ward" })).toBeVisible();
});

test("sign-in in the night theme (a nurse signed out at night) passes axe too", async ({
  page,
}) => {
  await setMockOptions(page, { google: true });
  await page.addInitScript(() => {
    localStorage.setItem("theme", "night");
  });
  await page.goto("/sign-in?error=no_access");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "night");
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page.getByText("Demo PIN: 135790")).toBeVisible();
  await expect(page.getByRole("link", { name: "Sign in with Google" })).toBeVisible();
  await checkScreen(page);
  await shot(page, "sign-in-night");
});

test("the other two refusals read plainly", async ({ page }) => {
  await setMockOptions(page, { google: true });
  await page.goto("/sign-in?error=expired");
  await expect(page.getByRole("alert")).toContainText("took too long");
  await checkScreen(page);
  await shot(page, "sign-in-expired");
  await page.goto("/sign-in?error=cancelled");
  await expect(page.getByRole("alert")).toContainText("was cancelled");
});

test("the demo banner stays on a signed-in screen, outside the header", async ({ page }) => {
  await signInAsSarah(page);
  await expect(page.getByText(DEMO_BANNER_TEXT)).toBeVisible();
  await expect(page.getByRole("banner").getByText(DEMO_BANNER_TEXT)).toHaveCount(0);
  await expectHeaderAtMostTwoRows(page);
  await checkScreen(page, { night: true });
  await shot(page, "patients-banner");
});

test("changes the shift from the header, with the picker open, without sideways scroll", async ({
  page,
}) => {
  await signInAsSarah(page);
  await page.getByRole("button", { name: "Change shift" }).click();
  await expect(page.getByRole("button", { name: /^2-10/ })).toBeVisible();
  await noSidewaysScroll(page);
  await page.getByRole("button", { name: /^2-10/ }).click();
  await expect(page.getByText("Shift 2-10")).toBeVisible();
  await expect(page.getByText("14:00 to 22:00 11 Nov 2026")).toBeVisible();
});
