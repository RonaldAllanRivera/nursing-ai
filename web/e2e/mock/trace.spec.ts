// The trace view for demo patient A's note against the mock API, at 375, 768 and 1280 px.
// The mock keeps its state in the page, so the note is reached the way a nurse reaches it: save a
// rough note and follow the draft (a full reload would sign the mock out).
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];
const SARAH = "Staff nurse · Sarah Navarro, RN";

async function noSidewaysScroll(page: Page) {
  const fits = await page.evaluate(
    () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
  );
  expect(fits).toBe(true);
}

async function openDemoNote(page: Page, patient: RegExp = /Demo patient A/) {
  await page.goto("/sign-in");
  await page.getByRole("button", { name: SARAH }).click();
  await page.getByRole("link", { name: patient }).click();
  await page.getByLabel("Your note").fill("pt c/o hilo since 2am, BP 90/60 HR 112");
  await page.getByRole("button", { name: "Save note" }).click();
  await expect(page).toHaveURL(/\/notes\/[0-9a-f-]{36}$/, { timeout: 8000 });
  await expect(page.getByRole("heading", { name: "Your note" })).toBeVisible();
}

const line = (page: Page, words: RegExp) => page.getByRole("button", { name: words });
const D2 = /^BP 90\/60 mmHg, HR 121 bpm\./;
const isSmall = (page: Page) => (page.viewportSize()?.width ?? 0) < 960;

test("shows the note, the draft and the answer, and fits the screen", async ({ page }) => {
  await openDemoNote(page);
  await expect(page.getByRole("heading", { name: /^Demo patient A/, level: 1 })).toBeVisible();
  await expect(
    page.getByText(
      "64 F, Medical Ward. FDAR note for the 10-6 shift, 22:00 11 Nov to 06:00 12 Nov 2026.",
    ),
  ).toBeVisible();
  await expect(page.getByText("Typed at 05:10. The AI never changes it.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "FDAR draft" })).toBeVisible();
  await expect(page.getByText("3 lines need you before you sign.")).toBeVisible();
  await expect(page.getByText("Not written — left empty")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Missing from this note" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign note" })).toBeVisible();
  await noSidewaysScroll(page);
});

test("selecting a line lights up its words in the note, with the differing number marked", async ({
  page,
}) => {
  await openDemoNote(page);
  await line(page, D2).click();
  await expect(page).toHaveURL(/\?line=e1-D2$/);
  const mark = page.locator(".note-text mark.hl");
  await expect(mark).toHaveCount(1);
  await expect(mark).toHaveText("BP 90/60 HR 112");
  await expect(mark).toBeVisible();
  await expect(mark.locator(".num-bad")).toHaveText("112");
  // The highlight colour is painted (the highlighter's gradient), not just present in the markup.
  await expect
    .poll(() => mark.evaluate((el) => getComputedStyle(el).backgroundImage))
    .toContain("linear-gradient");
  const card = page.getByRole("complementary", { name: /came from/ });
  await expect(card.getByRole("heading", { name: "Number differs" })).toBeVisible();
  await expect(card.getByText("The draft says 121. Your note says 112.")).toBeVisible();
  await noSidewaysScroll(page);
});

test("a line without a source says so, and a small screen's drawer closes with Close", async ({
  page,
}) => {
  await openDemoNote(page);
  await line(page, /^Physician notified/).click();
  const card = page.getByRole("complementary", { name: /came from/ });
  await expect(card.getByText("No words in your note match this line.")).toBeVisible();
  await expect(page.locator(".note-text mark.hl")).toHaveCount(0);
  if (isSmall(page)) {
    await card.getByRole("button", { name: "Close" }).click();
    await expect(card).toBeHidden();
    await expect(line(page, /^Physician notified/)).toBeFocused();
    await expect(page).not.toHaveURL(/line=/);
  }
});

test("works by keyboard: Tab to the draft, arrow to a line, Escape, then Sign note", async ({
  page,
}) => {
  await openDemoNote(page);
  const first = line(page, /^Dizziness with low blood pressure/);
  for (let i = 0; i < 30; i++) {
    await page.keyboard.press("Tab");
    if (await first.evaluate((el) => el === document.activeElement)) break;
  }
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
  for (let i = 0; i < 30; i++) {
    await page.keyboard.press("Tab");
    if (await sign.evaluate((el) => el === document.activeElement)) break;
  }
  await expect(sign).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator(".line[aria-current='true']")).toBeFocused();
  await expect(page.getByRole("status")).toHaveText("Check this line before you sign.");
});

test("has no axe violations with a line selected, in day and in night", async ({ page }) => {
  await openDemoNote(page);
  const empty = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  expect(empty.violations).toEqual([]);
  await line(page, D2).click();
  await expect(page.locator(".note-text mark.hl")).toBeVisible();
  const day = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  expect(day.violations).toEqual([]);
  await page.getByRole("button", { name: "Night theme" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "night");
  const night = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  expect(night.violations).toEqual([]);
  await noSidewaysScroll(page);
});

test("demo-2's two entries, and a line left empty, have no axe violations in day and night", async ({
  page,
}) => {
  await openDemoNote(page, /Demo patient B/);
  await expect(page.getByRole("button", { name: /^Fever/ })).toBeVisible();
  await expect(page.getByText("Not written — left empty")).toBeVisible();
  const day = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  expect(day.violations).toEqual([]);
  await page.getByRole("button", { name: "Night theme" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "night");
  const night = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  expect(night.violations).toEqual([]);
  await noSidewaysScroll(page);
});
