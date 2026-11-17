// Helpers every mock-API spec shares. The mock keeps its state in the page, so a flow never
// reloads: it navigates inside the app, the way a nurse does.
import AxeBuilder from "@axe-core/playwright";
import { expect, type Locator, type Page } from "@playwright/test";

export const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];
export const SARAH = "Staff nurse · Sarah Navarro, RN";
export const EMILY = "Staff nurse · Emily Carter, RN";
export const ADMIN = "Admin · Victor Lazaro";

export const ROUGH_NOTE = "pt c/o hilo since 2am, BP 90/60 HR 112";

export const FOCUS = /^Dizziness with low blood pressure/;
export const D2 = /^BP 90\/60 mmHg, HR 121/;
export const PHYSICIAN = /^Physician notified/;

export const line = (page: Page, words: RegExp) => page.getByRole("button", { name: words });
export const card = (page: Page) => page.getByRole("complementary", { name: /came from/ });
export const isSmall = (page: Page) => (page.viewportSize()?.width ?? 0) < 960;

export async function noSidewaysScroll(page: Page) {
  const fits = await page.evaluate(
    () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
  );
  expect(fits).toBe(true);
}

export async function expectNoViolations(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  expect(results.violations).toEqual([]);
}

/** Axe in the day theme, then in the night theme; the page is put back to day afterwards. */
export async function expectNoViolationsDayAndNight(page: Page) {
  await expectNoViolations(page);
  const toggle = page.getByRole("button", { name: "Night theme" });
  await toggle.click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "night");
  await expectNoViolations(page);
  await toggle.click();
  await expect(page.locator("html")).not.toHaveAttribute("data-theme", "night");
}

/**
 * Full-page screenshots of the flow's screens, for review: only when `E2E_SHOTS` names a folder.
 * The normal run skips it, so it costs nothing.
 */
export async function shot(page: Page, screen: string) {
  const folder = process.env["E2E_SHOTS"];
  if (!folder) return;
  const width = page.viewportSize()?.width ?? 0;
  await page.screenshot({ path: `${folder}/shot-${screen}-${String(width)}.png`, fullPage: true });
}

/**
 * The header takes at most two rows (on a phone: who is signed in and Sign out, then the shift,
 * the link and the theme). Rows are counted from the vertical centres of the header's controls
 * and its name line: a gap of more than 20 px between two centres starts a new row.
 */
export async function expectHeaderAtMostTwoRows(page: Page) {
  const centres = await page.getByRole("banner").evaluate((header) =>
    [...header.querySelectorAll("button, a, p")]
      .map((el) => el.getBoundingClientRect())
      .filter((box) => box.width > 0 && box.height > 0)
      .map((box) => box.top + box.height / 2)
      .sort((a, b) => a - b),
  );
  expect(centres.length).toBeGreaterThan(3);
  let rows = 1;
  for (let i = 1; i < centres.length; i++) {
    if ((centres[i] ?? 0) - (centres[i - 1] ?? 0) > 20) rows++;
  }
  expect(rows, `centres: ${centres.map(Math.round).join(", ")}`).toBeLessThanOrEqual(2);

  // And nothing sits on top of anything else: no two controls or the name line overlap.
  const overlaps = await page.getByRole("banner").evaluate((header) => {
    const boxes = [...header.querySelectorAll("button, a, p")].map((el) =>
      el.getBoundingClientRect(),
    );
    let found = 0;
    for (const [i, a] of boxes.entries()) {
      for (const b of boxes.slice(i + 1)) {
        const across = Math.min(a.right, b.right) - Math.max(a.left, b.left);
        const down = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
        if (across > 1 && down > 1) found++;
      }
    }
    return found;
  });
  expect(overlaps).toBe(0);
}

/** What every screen of a journey must pass: it fits, and axe finds nothing (day, and night if asked). */
export async function checkScreen(page: Page, opts: { night?: boolean } = {}) {
  await noSidewaysScroll(page);
  if (opts.night) await expectNoViolationsDayAndNight(page);
  else await expectNoViolations(page);
}

/** Tab (never click) until `target` has the focus, failing if it never does. */
export async function tabTo(page: Page, target: Locator, limit = 80) {
  for (let i = 0; i < limit; i++) {
    if (await target.evaluate((el) => el === document.activeElement)) return;
    await page.keyboard.press("Tab");
  }
  await expect(target).toBeFocused();
}

export async function signInAs(page: Page, persona: string, landing: string) {
  await page.goto("/sign-in");
  await page.getByRole("button", { name: persona }).click();
  await expect(page.getByRole("heading", { name: landing })).toBeVisible();
}

export async function signInAsSarah(page: Page) {
  await signInAs(page, SARAH, "Patients on this ward");
}

export async function openPatient(page: Page, patient: RegExp = /Demo patient A/) {
  await signInAsSarah(page);
  await page.getByRole("link", { name: patient }).click();
  await expect(page.getByRole("heading", { name: patient })).toBeVisible();
}

/** Sign in as Sarah, open the patient, save a rough note and follow the draft to its note. */
export async function openDemoNote(page: Page, patient: RegExp = /Demo patient A/) {
  await openPatient(page, patient);
  await page.getByLabel("Your note").fill(ROUGH_NOTE);
  await page.getByRole("button", { name: "Save note" }).click();
  await expect(page).toHaveURL(/\/notes\/[0-9a-f-]{36}$/, { timeout: 8000 });
  await expect(page.getByRole("heading", { name: "Your note" })).toBeVisible();
}

/** Demo patient A's three lines: confirm the Focus, use 112, remove "Physician notified". */
export async function resolveThreeLines(page: Page) {
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

/** The page's own status line: the app-wide "waking" line is a status too, and is not what a spec means. */
export const pageStatus = (page: Page) => page.locator('[role="status"]:not(#waking-notice)');
