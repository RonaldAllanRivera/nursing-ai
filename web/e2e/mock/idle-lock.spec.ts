// The browser's own idle lock and the session's hard end, against the mock API at 375, 768 and
// 1280 px. `page.clock` passes the time: it drives the page's timers and `Date.now()`, which is
// also what the mock's own idle clock reads.
import { expect, test } from "@playwright/test";
import {
  ROUGH_NOTE,
  SARAH,
  checkScreen,
  enterDemoPin,
  expectHeaderAtMostTwoRows,
  openPatient,
  setMockOptions,
  shot,
  tabTo,
} from "./helpers.ts";

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;

test("lock and unlock at 375 px keeps the typed note and hides the patient", async ({ page }) => {
  await page.clock.install();
  await openPatient(page);
  const note = page.getByLabel("Your note");
  await note.focus();
  await page.keyboard.type(ROUGH_NOTE);
  await expect(note).toHaveValue(ROUGH_NOTE);

  // Five minutes with nobody at the screen.
  await page.clock.fastForward(5 * MINUTE + 1000);
  await expect(page.getByRole("heading", { name: /^Enter your PIN, / })).toBeVisible();
  await expect(page.getByText("Locked after 5 minutes without use.")).toBeVisible();
  // Not one patient detail is left in the page, or in the typed note's box.
  await expect(page.getByText(/Demo patient/)).toHaveCount(0);
  await expect(page.getByText(/\bBed\b/)).toHaveCount(0);
  await expect(page.getByLabel("Your note")).toHaveCount(0);
  expect(await page.locator("body").innerText()).not.toContain(ROUGH_NOTE);
  await checkScreen(page, { night: true });
  await shot(page, "idle-locked");

  // Unlock by keyboard: the note and the cursor are where she left them.
  await page.getByLabel("PIN", { exact: true }).focus();
  await enterDemoPin(page);
  await expect(page.getByLabel("Your note")).toHaveValue(ROUGH_NOTE);
  await expect(page.getByLabel("Your note")).toBeFocused();
  await expect(page.getByRole("heading", { name: /Demo patient A/ })).toBeVisible();
});

test("the header says Not you? Switch nurse during the lock and Switch nurse signs out", async ({
  page,
}) => {
  await page.clock.install();
  await openPatient(page);
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  await page.clock.fastForward(5 * MINUTE + 1000);
  await expect(page.getByRole("heading", { name: /^Enter your PIN, / })).toBeVisible();

  const header = page.getByRole("banner");
  await expect(header.getByText("Not you?")).toBeVisible();
  await expect(header.getByText("Sarah Navarro, RN")).toBeVisible();
  await expect(header.getByRole("button", { name: "Sign out" })).toHaveCount(0);
  await expect(header.getByRole("button", { name: "Change shift" })).toHaveCount(0);
  await expect(header.getByRole("link")).toHaveCount(0);
  await expectHeaderAtMostTwoRows(page);
  await shot(page, "header-gate");

  // By keyboard only.
  const switchNurse = header.getByRole("button", { name: "Switch nurse" });
  await tabTo(page, switchNurse, 10);
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await expect(page).toHaveURL(/\/sign-in$/);
  await expect(page.getByRole("button", { name: SARAH })).toBeVisible();
});

test("a session past its hours ends with the hours said on the sign-in screen", async ({
  page,
}) => {
  await page.clock.install();
  await openPatient(page);
  await page.clock.fastForward(12 * HOUR + MINUTE);
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await expect(page.getByRole("alert")).toHaveText(
    "Your session ended after 12 hours. Sign in again.",
  );
  await expect(page.getByText(/Demo patient/)).toHaveCount(0);
  await checkScreen(page, { night: false });
  await shot(page, "session-ended");

  // A way to sign in is right there, and works.
  await page.getByRole("button", { name: SARAH }).click();
  await enterDemoPin(page);
  await expect(page.getByRole("heading", { name: "Patients on this ward" })).toBeVisible();
  await expect(page.getByText(/session ended/)).toHaveCount(0);
});

test("a PIN-locked session says what happens next", async ({ page }) => {
  await setMockOptions(page, { account: { user: "lito.santos@example.com" } });
  await page.goto("/patients");
  await expect(
    page.getByText("Once it's reset, choose Switch nurse above and sign in again."),
  ).toBeVisible();
  await expectHeaderAtMostTwoRows(page);
  await checkScreen(page, { night: true });
  await shot(page, "pin-locked-next");
});
