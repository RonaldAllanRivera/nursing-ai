// End-to-end check of the start page against the real API (run `make e2e`).
// Every test runs at 375, 768 and 1280 px wide (see playwright.config.ts).
// There is no keyboard-path test yet: the page has nothing to focus (no link,
// button or field), so there is no tab order to check. Add one with the first
// interactive control.
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("shows API: healthy against the real API", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("status")).toHaveText("API: healthy");
});

test("has no axe violations", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("status")).toHaveText("API: healthy");
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
  expect(results.violations).toEqual([]);
});

test("has no sideways scroll", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("status")).toHaveText("API: healthy");
  const fits = await page.evaluate(
    () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
  );
  expect(fits).toBe(true);
});
