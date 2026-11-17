// The trace view's edge cases against the mock API, at 375, 768 and 1280 px: a line with no source
// and the small screen's drawer, the arrow-key path, and demo-2's entries. The note, the selected
// line and axe on the trace view are steps of the PH flow in journeys.spec.ts. The mock keeps its
// state in the page, so the note is reached the way a nurse reaches it (a full reload would sign
// the mock out).
import { expect, test } from "@playwright/test";
import {
  D2,
  card,
  expectNoViolationsDayAndNight,
  isSmall,
  line,
  noSidewaysScroll,
  pageStatus,
  openDemoNote,
  tabTo,
} from "./helpers.ts";

test("a line without a source says so, and a small screen's drawer closes with Close", async ({
  page,
}) => {
  await openDemoNote(page);
  await line(page, /^Physician notified/).click();
  await expect(card(page).getByText("No words in your note match this line.")).toBeVisible();
  await expect(page.locator(".note-text mark.hl")).toHaveCount(0);
  if (isSmall(page)) {
    await card(page).getByRole("button", { name: "Close" }).click();
    await expect(card(page)).toBeHidden();
    await expect(line(page, /^Physician notified/)).toBeFocused();
    await expect(page).not.toHaveURL(/line=/);
  }
});

test("works by keyboard: Tab to the draft, arrow to a line, Escape, then Sign note", async ({
  page,
}) => {
  await openDemoNote(page);
  const first = line(page, /^Dizziness with low blood pressure/);
  await tabTo(page, first, 30);
  await expect(first).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  await expect(line(page, D2)).toBeFocused();
  await expect(page).toHaveURL(/\?line=e1-D2$/);
  await expect(page.locator(".note-text mark.hl")).toHaveText("BP 90/60 HR 112");
  await page.keyboard.press("End");
  await expect(line(page, /^Still weak/)).toBeFocused();
  await page.keyboard.press("Home");
  await expect(first).toBeFocused();

  if (isSmall(page)) {
    // The focus is in the drawer, so Escape has to bring it back to the line.
    await page.getByRole("button", { name: "Close" }).focus();
    await page.keyboard.press("Escape");
    await expect(page).not.toHaveURL(/line=/);
    await expect(first).toBeFocused();
  }

  const sign = page.getByRole("button", { name: "Sign note" });
  await tabTo(page, sign, 30);
  await expect(sign).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator(".line[aria-current='true']")).toBeFocused();
  await expect(pageStatus(page)).toHaveText("Check this line before you sign.");
});

test("demo-2's two entries, and a line left empty, have no axe violations in day and night", async ({
  page,
}) => {
  await openDemoNote(page, /Demo patient B/);
  await expect(page.getByRole("button", { name: /^Fever/ })).toBeVisible();
  await expect(page.getByText("Not written — left empty")).toBeVisible();
  await expectNoViolationsDayAndNight(page);
  await noSidewaysScroll(page);
});
