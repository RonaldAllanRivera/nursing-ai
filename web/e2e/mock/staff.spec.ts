// The Staff screen against the mock API, at 375, 768 and 1280 px: the admin invites and resets a
// locked PIN by keyboard, revokes, and a head nurse sees her own facility and can only reset PINs.
import { expect, test, type Page } from "@playwright/test";
import {
  checkDialog,
  checkScreen,
  noSidewaysScroll,
  pageStatus,
  setMockOptions,
  shot,
  tabTo,
} from "./helpers.ts";

const ADMIN = "dana.admin@example.com";
const HEAD = "hana.reyes@example.com";
// Every mock Google user's PIN (MOCK_PIN in src/mocks/staff.ts; the e2e project does not import app code).
const PIN = "246813";

async function openStaff(page: Page, user: string) {
  await setMockOptions(page, { account: { user, gate: "open" } });
  await page.goto("/staff");
  await expect(page.getByRole("heading", { name: "Staff", level: 1 })).toBeVisible();
  await expect(page.getByRole("list", { name: "Staff" })).toBeVisible();
}

/** The PIN field has the focus (or Cancel does, for a revoke: then Shift+Tab goes back to it). */
async function typePin(page: Page, name: string | RegExp) {
  const dialog = page.getByRole("dialog", { name });
  await expect(dialog).toBeVisible();
  const field = dialog.getByLabel("Your PIN");
  if (!(await field.evaluate((el) => el === document.activeElement))) await tabTo(page, field);
  await page.keyboard.type(PIN);
  await page.keyboard.press("Enter");
}

const rowOf = (page: Page, name: string) =>
  page.getByRole("list", { name: "Staff" }).getByRole("listitem").filter({ hasText: name });

test("the admin's list puts the locked PIN first, and fits at every width, day and night", async ({
  page,
}) => {
  await openStaff(page, ADMIN);
  await expect(page.getByRole("link", { name: "Staff" })).toBeVisible();
  const first = page.getByRole("list", { name: "Staff" }).getByRole("listitem").first();
  await expect(first).toContainText("Lito Santos");
  await expect(first).toContainText("PIN locked");
  await expect(rowOf(page, "Rita Moore")).toContainText("Revoked");
  await expect(rowOf(page, "Irene Lim")).toContainText("Invited");
  await expect(rowOf(page, "Dana Admin").getByRole("button")).toHaveCount(0);
  await checkScreen(page, { night: true });
  await shot(page, "staff-admin");
});

test("the admin invites someone by keyboard only", async ({ page }) => {
  await openStaff(page, ADMIN);
  const email = page.getByLabel("Email");
  await tabTo(page, email);
  await page.keyboard.type("New.Nurse@Example.com");
  // The form is checked first: no facility yet, so no PIN is asked for.
  await page.keyboard.press("Enter");
  await expect(page.getByText("Choose the facility this nurse works at.")).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await checkScreen(page);
  await shot(page, "staff-invite-problem");

  const facility = page.getByLabel("Facility");
  await tabTo(page, facility);
  await facility.selectOption("us-demo");
  await tabTo(page, page.getByRole("button", { name: "Invite" }));
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog", { name: "Invite New.Nurse@Example.com?" })).toBeVisible();
  await checkDialog(page);
  await shot(page, "staff-invite-pin");
  await typePin(page, "Invite New.Nurse@Example.com?");

  await expect(pageStatus(page)).toContainText("new.nurse@example.com is invited.");
  await expect(rowOf(page, "new.nurse@example.com")).toContainText("Invited");
  await expect(email).toBeFocused();
  await expect(email).toHaveValue("");
  await checkScreen(page, { night: true });
});

test("the admin resets a locked PIN by keyboard only", async ({ page }) => {
  await openStaff(page, ADMIN);
  const reset = page.getByRole("button", { name: "Reset PIN for Lito Santos" });
  await tabTo(page, reset);
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog", { name: "Reset Lito Santos's PIN?" })).toContainText(
    "They will choose a new one at their next sign-in.",
  );
  await checkDialog(page);
  await typePin(page, "Reset Lito Santos's PIN?");
  await expect(pageStatus(page)).toContainText("Lito Santos's PIN is reset.");
  await expect(rowOf(page, "Lito Santos")).not.toContainText("PIN locked");
  await expect(reset).toBeFocused();
  await checkScreen(page, { night: true });
});

test("a revoke asks with the safe choice focused, and a wrong PIN says the tries left", async ({
  page,
}) => {
  await openStaff(page, ADMIN);
  const revoke = page.getByRole("button", { name: "Revoke Paolo Cruz's access" });
  await tabTo(page, revoke);
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "Revoke Paolo Cruz's access?" });
  await expect(dialog.getByRole("button", { name: "Cancel" })).toBeFocused();
  await shot(page, "staff-revoke");
  await tabTo(page, dialog.getByLabel("Your PIN"));
  await page.keyboard.type("111111");
  await page.keyboard.press("Enter");
  await expect(dialog).toContainText("Wrong PIN. 4 tries left.");
  await checkDialog(page);
  await expect(dialog.getByLabel("Your PIN")).toBeFocused();
  await page.keyboard.type(PIN);
  await page.keyboard.press("Enter");
  await expect(pageStatus(page)).toContainText("Paolo Cruz's access is revoked.");
  await expect(rowOf(page, "Paolo Cruz")).toContainText("Revoked");
  await expect(rowOf(page, "Paolo Cruz").getByRole("button")).toHaveCount(0);
  // The pressed button is gone with the action: the row takes the focus.
  await expect(rowOf(page, "Paolo Cruz")).toBeFocused();
  await noSidewaysScroll(page);
});

test("a head nurse sees her facility, no invite and no revoke, and resets a PIN", async ({
  page,
}) => {
  await openStaff(page, HEAD);
  await expect(page.getByRole("heading", { name: "Invite someone" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /^Revoke/ })).toHaveCount(0);
  await expect(page.getByText("Rita Moore")).toHaveCount(0);
  await expect(page.getByText("Sam Porter")).toHaveCount(0);
  await expect(rowOf(page, "Hana Reyes").getByRole("button")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Patients" })).toBeVisible();
  await checkScreen(page, { night: true });
  await shot(page, "staff-head");

  await page.getByRole("button", { name: "Reset PIN for Lito Santos" }).focus();
  await page.keyboard.press("Enter");
  await typePin(page, "Reset Lito Santos's PIN?");
  await expect(pageStatus(page)).toContainText("Lito Santos's PIN is reset.");
  await expect(rowOf(page, "Lito Santos")).not.toContainText("PIN locked");
});

test("a staff nurse who opens /staff lands on her patients", async ({ page }) => {
  await setMockOptions(page, { account: { user: "paolo.cruz@example.com", gate: "open" } });
  await page.goto("/staff");
  await expect(page.getByRole("heading", { name: "Patients on this ward" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Staff" })).toHaveCount(0);
});
