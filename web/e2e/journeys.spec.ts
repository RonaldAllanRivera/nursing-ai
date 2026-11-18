// The journeys against the real stack: Postgres, the API and the web app's /api proxy (`make e2e`).
// Each test signs in through the screens as a demo persona. The database keeps its data between
// runs, so nothing assumes an empty one, and no assertion depends on the draft's wording: in replay
// mode the draft is the live model's own.
//
//   1. The PH flow at 375, 768 and 1280 px, by pointer.
//   2. The same flow by keyboard alone (1280 px).
//   3. The US path (375 px).
//   4. The admin path, and the one-origin check: the sign and the settings save both answered 2xx.
import { expect, test } from "@playwright/test";
import {
  ADMIN,
  EMILY,
  checkScreen,
  demoNoteText,
  draftLines,
  editOneLine,
  expectNoViolations,
  noSidewaysScroll,
  pageStatus,
  SAVE_PIN_DIALOG,
  enterPinInDialog,
  openPatient,
  resolveEveryLine,
  saveNote,
  seeSourceHighlight,
  signInAs,
  signNote,
  tabTo,
  walkLinesByArrows,
} from "./real/helpers.ts";
import { widths } from "./widths.ts";

const projectAt = (width: number) => {
  const found = widths.find((w) => w.width === width);
  if (!found) throw new Error(`No project at ${String(width)} px in widths.ts.`);
  return found.name;
};

test("PH flow: write demo-1's note, check every line, edit one, sign, see it locked", async ({
  page,
}) => {
  await openPatient(page, "Demo patient A");
  await checkScreen(page);
  await saveNote(page, demoNoteText("demo-1"));
  await expect(page.getByRole("heading", { name: "FDAR draft" })).toBeVisible();
  await checkScreen(page);

  await seeSourceHighlight(page);
  await resolveEveryLine(page);
  await editOneLine(page);
  await noSidewaysScroll(page);
  await expectNoViolations(page);

  const response = await signNote(page);
  expect(response.ok()).toBe(true);
  await expect(page.getByRole("button", { name: /Sign note|Discard draft/ })).toHaveCount(0);
  await checkScreen(page);
});

test("PH flow by keyboard alone: Tab, Enter, arrows and Escape", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== projectAt(1280), "The keyboard path runs at 1280 px only.");
  await page.goto("/sign-in");
  await tabTo(page, page.getByRole("button", { name: "Staff nurse · Sarah Navarro, RN" }), 10);
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Patients on this ward" })).toBeVisible();
  const row = page.getByRole("link", { name: /Demo patient A/ });
  await tabTo(page, row, 12);
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Demo patient A" })).toBeVisible();
  // "Notes this shift" comes first in the tab order, with a link for every note of the shift.
  await expect(page.getByRole("region", { name: "Notes this shift" })).toBeVisible();
  const earlier = await page.locator('[aria-labelledby="shift-notes-heading"] a').count();
  await tabTo(page, page.getByLabel("Your note"), 40 + earlier);
  await saveNote(page, demoNoteText("demo-1"), { keyboard: true });
  await checkScreen(page);

  await walkLinesByArrows(page);
  await resolveEveryLine(page, "keyboard");
  await editOneLine(page, "keyboard");

  // Sign note opens the dialog on the safe choice; Escape cancels it and the focus goes back.
  const sign = page.getByRole("button", { name: "Sign note" });
  await tabTo(page, sign);
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: /^Sign this (FDAR|DAR) note$/ });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Cancel" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(sign).toBeFocused();

  const response = await signNote(page, "keyboard");
  expect(response.ok()).toBe(true);
  await checkScreen(page);
});

test("US path: DAR draft, shift 7a-7p or 7p-7a, times in Pacific time", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== projectAt(375), "The US path runs at 375 px only.");
  const pacific = (when: Date) =>
    new Intl.DateTimeFormat("en-US", {
      timeZone: "America/Los_Angeles",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    }).format(when);

  await signInAs(page, EMILY, "Patients on this unit");
  await page.getByRole("link", { name: /Demo patient C/ }).click();
  await expect(page.getByRole("heading", { name: "Demo patient C" })).toBeVisible();
  // The shift is 7a-7p or 7p-7a, so its clock times are 07:00 and 19:00 in the facility's zone;
  // the browser's UTC would show 15:00 and 03:00 instead.
  await expect(
    page.getByRole("main").getByText(/\b(07:00|19:00)\b.* to (07:00|19:00)\b/),
  ).toBeVisible();

  // The note is stamped with the time it was saved, read in the facility's zone.
  const before = new Date(Date.now() - 60_000);
  await saveNote(page, demoNoteText("demo-3"));
  const after = new Date(Date.now() + 60_000);
  // Every minute from just before the save to just after it, so a minute change can't fail it.
  const typedAt: string[] = [];
  for (let at = before.getTime(); at <= after.getTime() + 60_000; at += 60_000) {
    typedAt.push(pacific(new Date(at)));
  }
  await expect(page.getByText(/^Typed at \d\d:\d\d\. The AI never changes it\.$/)).toHaveText(
    new RegExp(`^Typed at (${[...new Set(typedAt)].join("|")})\\.`),
  );
  await expect(page.getByRole("heading", { name: "DAR draft" })).toBeVisible();
  await expect(page.getByText("FDAR")).toHaveCount(0);
  // A DAR note has no Focus section.
  await expect(page.getByRole("heading", { name: /Focus/ })).toHaveCount(0);
  await expect(draftLines(page).first()).toBeVisible();
  await expect(page.getByRole("banner").getByText(/Shift 7(a-7p|p-7a)/)).toBeVisible();
  await checkScreen(page);
});

test("Admin path: save a facility's settings, then put the label back (one origin)", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name === projectAt(768), "The admin path runs at 375 and 1280 px.");
  await signInAs(page, ADMIN, "Settings");
  await expect(page.getByRole("textbox", { name: "Facility name" })).toBeVisible();
  const label = page.getByRole("group", { name: "Shift 3" }).getByLabel("Label");
  const original = await label.inputValue();
  const changed = original === "Night" ? "Late" : "Night";

  const save = async (value: string) => {
    await label.fill(value);
    const answered = page.waitForResponse(
      (r) =>
        r.request().method() === "PUT" &&
        new URL(r.url()).pathname.startsWith("/api/v1/facilities/"),
    );
    await page.getByRole("button", { name: "Save settings" }).click();
    // Saving asks for her own PIN first.
    await enterPinInDialog(page, SAVE_PIN_DIALOG);
    const response = await answered;
    // The ETag and the cookie went through the dev server's /api proxy: a 428 would mean they didn't.
    const sent = await response.request().allHeaders();
    expect(sent["if-match"]).toBeTruthy();
    expect(sent["cookie"]).toContain("sl_session=");
    expect(response.status()).toBeGreaterThanOrEqual(200);
    expect(response.status()).toBeLessThan(300);
    await expect(pageStatus(page)).toContainText("Saved.");
    await expect(label).toHaveValue(value);
  };

  await save(changed);
  await checkScreen(page);
  await save(original);
});

test("One origin: signing sends If-Match and the session cookie through the proxy", async ({
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name !== projectAt(1280),
    "The one-origin check runs at 1280 px only.",
  );
  await openPatient(page, "Demo patient A");
  await saveNote(page, demoNoteText("demo-1"));
  await resolveEveryLine(page);
  const response = await signNote(page);
  const sent = await response.request().allHeaders();
  expect(sent["if-match"]).toBeTruthy();
  expect(sent["cookie"]).toContain("sl_session=");
  expect(response.status()).toBeGreaterThanOrEqual(200);
  expect(response.status()).toBeLessThan(300);
});
