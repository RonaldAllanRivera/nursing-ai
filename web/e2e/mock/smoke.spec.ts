// The start page against the mock API, at 375, 768 and 1280 px (see playwright.mock.config.ts).
// No keyboard-path test yet: the page has nothing to focus. Add one with the first control.
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("loads the start page with its fonts", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Nursing Documentation AI" })).toBeVisible();
  await expect(page.getByRole("status")).toHaveText("API: healthy");
  await expect(
    page.getByText("Documentation aid — the nurse reviews and signs every note."),
  ).toBeVisible();
  const family = await page.evaluate(async () => {
    await document.fonts.ready;
    return document.fonts.check('16px "Atkinson Hyperlegible Next"');
  });
  expect(family).toBe(true);
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
