// W5 against the mock API, at 375, 768 and 1280 px: deal with demo-1's three lines, sign, see the
// lock and the hash; the same by keyboard alone; discard. The mock keeps its state in the page,
// so the note is reached the way a nurse reaches it (a full reload would sign the mock out).
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Locator, type Page } from "@playwright/test";

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];
const SARAH = "Staff nurse · Sarah Navarro, RN";

async function noSidewaysScroll(page: Page) {
  const fits = await page.evaluate(
    () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
  );
  expect(fits).toBe(true);
}

async function openDemoNote(page: Page) {
  await page.goto("/sign-in");
  await page.getByRole("button", { name: SARAH }).click();
  await page.getByRole("link", { name: /Demo patient A/ }).click();
  await page.getByLabel("Your note").fill("pt c/o hilo since 2am, BP 90/60 HR 112");
  await page.getByRole("button", { name: "Save note" }).click();
  await expect(page).toHaveURL(/\/notes\/[0-9a-f-]{36}$/, { timeout: 8000 });
  await expect(page.getByRole("heading", { name: "Your note" })).toBeVisible();
}

const FOCUS = /^Dizziness with low blood pressure/;
const D2 = /^BP 90\/60 mmHg, HR 121/;
const PHYSICIAN = /^Physician notified/;
const line = (page: Page, words: RegExp) => page.getByRole("button", { name: words });
const card = (page: Page) => page.getByRole("complementary", { name: /came from/ });

/** Tab (never click) until the control has the focus. */
async function tabTo(page: Page, target: Locator) {
  for (let i = 0; i < 80; i++) {
    if (await target.evaluate((el) => el === document.activeElement)) return;
    await page.keyboard.press("Tab");
  }
  await expect(target).toBeFocused();
}

async function resolveThreeLines(page: Page) {
  await line(page, FOCUS).click();
  await card(page).getByRole("button", { name: "Wording is right" }).click();
  await expect(line(page, FOCUS)).toContainText("Checked by you");
  await line(page, D2).click();
  await card(page).getByRole("button", { name: "Use 112 from your note" }).click();
  await expect(line(page, /^BP 90\/60 mmHg, HR 112 bpm/)).toContainText("Edited by you");
  await line(page, PHYSICIAN).click();
  await card(page).getByRole("button", { name: "Remove line" }).click();
  await expect(line(page, PHYSICIAN)).toContainText("Removed by you");
  await expect(page.getByText("All lines checked. Ready to sign.")).toBeVisible();
}

test("resolves the three lines, signs, and sees the lock and the hash", async ({ page }) => {
  await openDemoNote(page);
  await resolveThreeLines(page);
  await noSidewaysScroll(page);

  // On a small screen the drawer sits over the Sign bar: close it first, as the nurse would.
  if ((page.viewportSize()?.width ?? 0) < 960) {
    await card(page).getByRole("button", { name: "Close" }).click();
  }
  await page.getByRole("button", { name: "Sign note" }).click();
  const dialog = page.getByRole("dialog", { name: "Sign this FDAR note" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText("Not in this note:")).toBeVisible();
  await noSidewaysScroll(page);
  const open = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  expect(open.violations).toEqual([]);

  await dialog.getByRole("button", { name: "Sign note" }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByText(/^Signed by you at \d\d:\d\d\.$/)).toBeVisible();
  await expect(page.getByText(/^Note hash [0-9a-f]{12}$/)).toBeVisible();
  await expect(page.getByText("Signed. This note is locked.")).toBeVisible();
  await expect(page.getByRole("button", { name: /Sign note|Discard draft/ })).toHaveCount(0);
  // The removed line is not in the record.
  await expect(line(page, PHYSICIAN)).toHaveCount(0);
  await line(page, FOCUS).click();
  await expect(card(page).getByRole("button", { name: /Wording|Edit line|Undo/ })).toHaveCount(0);
  await noSidewaysScroll(page);

  const day = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  expect(day.violations).toEqual([]);
  await page.getByRole("button", { name: "Night theme" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "night");
  const night = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  expect(night.violations).toEqual([]);
});

test("does it all by keyboard: Tab to a line, Enter, Tab to the action, then sign", async ({
  page,
}) => {
  await openDemoNote(page);

  await tabTo(page, line(page, FOCUS));
  await page.keyboard.press("Enter");
  await tabTo(page, card(page).getByRole("button", { name: "Wording is right" }));
  await page.keyboard.press("Enter");
  await expect(line(page, FOCUS)).toContainText("Checked by you");
  await expect(line(page, FOCUS)).toBeFocused();

  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  await expect(line(page, D2)).toBeFocused();
  await tabTo(page, card(page).getByRole("button", { name: "Use 112 from your note" }));
  await page.keyboard.press("Enter");
  await expect(line(page, /^BP 90\/60 mmHg, HR 112 bpm/)).toContainText("Edited by you");

  await tabTo(page, line(page, PHYSICIAN));
  await page.keyboard.press("Enter");
  await tabTo(page, card(page).getByRole("button", { name: "Remove line" }));
  await page.keyboard.press("Enter");
  await expect(line(page, PHYSICIAN)).toContainText("Removed by you");

  // Sign note opens the dialog; Escape cancels it and the focus goes back.
  const sign = page.getByRole("button", { name: "Sign note" });
  await tabTo(page, sign);
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "Sign this FDAR note" });
  await expect(dialog).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(sign).toBeFocused();

  await page.keyboard.press("Enter");
  await expect(dialog).toBeVisible();
  // The focus is trapped in the dialog: Tab goes round its two buttons and never leaves.
  for (let i = 0; i < 4; i++) {
    await page.keyboard.press("Tab");
    expect(await dialog.evaluate((el) => el.contains(document.activeElement))).toBe(true);
  }
  await tabTo(page, dialog.getByRole("button", { name: "Sign note" }));
  await page.keyboard.press("Enter");
  await expect(page.getByText(/^Signed by you at \d\d:\d\d\.$/)).toBeVisible();
  await expect(page.getByText(/^Note hash [0-9a-f]{12}$/)).toBeVisible();
});

test("asks before it discards, and the discarded note has no actions", async ({ page }) => {
  await openDemoNote(page);
  await page.getByRole("button", { name: "Discard draft" }).click();
  const dialog = page.getByRole("dialog", { name: "Discard this draft?" });
  await expect(
    dialog.getByText("It won't reach the record. Your typed note stays saved."),
  ).toBeVisible();
  const open = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  expect(open.violations).toEqual([]);
  await dialog.getByRole("button", { name: "Keep draft" }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByText("3 lines need you before you sign.")).toBeVisible();

  await page.getByRole("button", { name: "Discard draft" }).click();
  await dialog.getByRole("button", { name: "Discard draft" }).click();
  await expect(page.getByText("Discarded. This draft won't reach the record.")).toBeVisible();
  await expect(page.getByRole("button", { name: /Sign note|Discard draft/ })).toHaveCount(0);
  const after = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  expect(after.violations).toEqual([]);
  await noSidewaysScroll(page);
});
