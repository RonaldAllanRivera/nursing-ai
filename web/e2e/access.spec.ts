// The access screens against the real stack: the PIN gate, the idle lock, choosing a PIN, the
// Staff screen and "Use the demo note". Google users are made through the API's test-only route
// (APP_ENV=test, as under `make e2e`); the last step of the run revokes every one of them.
import { expect, test, type Page } from "@playwright/test";
import {
  SARAH,
  TEST_PIN,
  checkScreen,
  demoNoteText,
  draftLines,
  enterDemoPin,
  noSidewaysScroll,
  openPatient,
  pageStatus,
  startTestSession,
  tearDownTestUsers,
  tabTo,
} from "./real/helpers.ts";
import { widths } from "./widths.ts";

const projectAt = (width: number) => {
  const found = widths.find((w) => w.width === width);
  if (!found) throw new Error(`No project at ${String(width)} px in widths.ts.`);
  return found.name;
};

const MINUTE = 60_000;

test.afterAll(async ({ browser }) => {
  const context = await browser.newContext({
    baseURL: `http://localhost:${process.env["WEB_PORT"] ?? ""}`,
  });
  try {
    await tearDownTestUsers(await context.newPage());
  } finally {
    await context.close();
  }
});

test("a persona enters the PIN: a wrong one counts the tries and empties the field", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== projectAt(375), "The PIN path runs at 375 px only.");
  await page.goto("/sign-in");
  await page.getByRole("button", { name: SARAH }).click();
  const field = page.getByLabel("PIN", { exact: true });
  await expect(field).toBeFocused();
  await page.keyboard.type("999999");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("alert")).toHaveText("Wrong PIN. 4 tries left.");
  await expect(field).toHaveValue("");
  await expect(field).toBeFocused();
  await checkScreen(page);
  await expect(page.getByText(/Demo patient/)).toHaveCount(0);

  await enterDemoPin(page);
  await expect(page.getByRole("heading", { name: "Patients on this ward" })).toBeVisible();
  await noSidewaysScroll(page);
});

test("lock and unlock at 375 px keeps the typed note and hides the patient", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== projectAt(375), "The lock path runs at 375 px only.");
  await page.clock.install();
  await openPatient(page, "Demo patient A");
  const note = page.getByLabel("Your note");
  await note.focus();
  const typed = "pt c/o hilo since 2am, not saved";
  await page.keyboard.type(typed);
  await expect(note).toHaveValue(typed);

  await page.clock.fastForward(5 * MINUTE + 10_000);
  await expect(page.getByRole("heading", { name: /^Enter your PIN, / })).toBeVisible();
  await expect(page.getByText("Locked after 5 minutes without use.")).toBeVisible();
  await expect(page.getByLabel("PIN", { exact: true })).toBeFocused();
  await expect(page.getByText(/Demo patient/)).toHaveCount(0);
  await expect(page.getByLabel("Your note")).toHaveCount(0);
  expect(await page.locator("body").innerText()).not.toContain(typed);
  await checkScreen(page);

  await enterDemoPin(page);
  await expect(page.getByLabel("Your note")).toHaveValue(typed);
  await expect(page.getByRole("heading", { name: /Demo patient A/ })).toBeVisible();
});

test("a Google user with no PIN chooses one, typed twice, and lands on her ward", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== projectAt(375), "Choosing a PIN runs at 375 px only.");
  await startTestSession(page, { role: "staff_nurse", facilityKey: "ph-demo" });
  await page.goto("/patients");
  await expect(page.getByRole("heading", { name: /^Choose a PIN, / })).toBeVisible();
  await expect(page.getByText(/Demo PIN/)).toHaveCount(0);
  await expect(page.getByLabel("New PIN")).toBeFocused();
  await checkScreen(page);

  await page.keyboard.type("135792");
  await page.keyboard.press("Tab");
  await page.keyboard.type("135793");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("alert")).toHaveText("The two PINs don't match.");

  await page.getByLabel("New PIN").fill(TEST_PIN);
  await page.getByLabel("Type it again").fill(TEST_PIN);
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Patients on this ward" })).toBeVisible();
  await noSidewaysScroll(page);
});

const rowOf = (page: Page, name: string) =>
  page.getByRole("list", { name: "Staff" }).getByRole("listitem").filter({ hasText: name });

/** Type the test PIN in the dialog (the field has the focus, or Cancel does for a revoke). */
async function typePin(page: Page, name: string | RegExp) {
  const dialog = page.getByRole("dialog", { name });
  await expect(dialog).toBeVisible();
  const field = dialog.getByLabel("Your PIN");
  if (!(await field.evaluate((el) => el === document.activeElement))) await tabTo(page, field);
  await page.keyboard.type(TEST_PIN);
  await page.keyboard.press("Enter");
}

test("the admin sees the Staff list, invites an e2e address and revokes it", async ({ page }) => {
  await startTestSession(page, { role: "admin", facilityKey: null, pin: TEST_PIN });
  await page.goto("/staff");
  await expect(page.getByLabel("PIN", { exact: true })).toBeFocused();
  await page.keyboard.type(TEST_PIN);
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Staff", level: 1 })).toBeVisible();
  await expect(page.getByRole("list", { name: "Staff" })).toBeVisible();
  await checkScreen(page);

  const address = `e2e-${crypto.randomUUID()}@example.com`;
  await page.getByLabel("Email").fill(address);
  await page.getByLabel("Facility").selectOption("ph-demo");
  await page.getByRole("button", { name: "Invite" }).click();
  await typePin(page, `Invite ${address}?`);
  await expect(pageStatus(page)).toContainText(`${address} is invited.`);
  await expect(rowOf(page, address)).toContainText("Invited");
  await checkScreen(page);

  await rowOf(page, address)
    .getByRole("button", { name: /^Revoke/ })
    .click();
  const dialog = page.getByRole("dialog", { name: /^Revoke .* access\?$/ });
  await expect(dialog.getByRole("button", { name: "Cancel" })).toBeFocused();
  await typePin(page, /^Revoke .* access\?$/);
  await expect(pageStatus(page)).toContainText("is revoked.");
  await expect(rowOf(page, address)).toContainText("Revoked");
  await noSidewaysScroll(page);
});

test("Use the demo note fills the box with demo-1's note, saves it and shows the draft", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== projectAt(375), "The demo-note path runs at 375 px only.");
  await openPatient(page, "Demo patient A");
  await page.getByRole("button", { name: "Use the demo note" }).click();
  const expected = demoNoteText("demo-1");
  await expect(page.getByLabel("Your note")).toHaveValue(expected);
  await page.getByRole("button", { name: "Save note" }).click();
  await expect(page).toHaveURL(/\/notes\/[0-9a-f-]{36}$/, { timeout: 90_000 });
  await expect(page.getByRole("heading", { name: "Your note" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "FDAR draft" })).toBeVisible();
  await expect(draftLines(page).first()).toBeVisible();
});
