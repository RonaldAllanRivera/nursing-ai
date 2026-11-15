// The start page against the mock API, at 375, 768 and 1280 px (see playwright.mock.config.ts).
// No keyboard-path test yet: the page has nothing to focus. Add one with the first control.
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("loads the start page with its fonts", async ({ page }) => {
  const fonts = ["AtkinsonHyperlegibleNext-latin.woff2", "AtkinsonHyperlegibleMono-latin.woff2"];
  const loaded = fonts.map((file) =>
    page.waitForResponse((response) => response.url().endsWith(`/fonts/${file}`)),
  );
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Nursing Documentation AI" })).toBeVisible();
  await expect(page.getByRole("status")).toHaveText("API: healthy");
  await expect(
    page.getByText("Documentation aid — the nurse reviews and signs every note."),
  ).toBeVisible();
  // Ask for both faces (the page may not use Mono yet), then require a 200 for each file and a
  // loaded FontFace. `document.fonts.check()` is true even when no face matches, so it proves nothing.
  const status = await page.evaluate(async () => {
    await Promise.all([
      document.fonts.load('16px "Atkinson Hyperlegible Next"'),
      document.fonts.load('16px "Atkinson Hyperlegible Mono"'),
    ]);
    return [...document.fonts].map((face) => `${face.family.replaceAll('"', "")}:${face.status}`);
  });
  expect(status).toContain("Atkinson Hyperlegible Next:loaded");
  expect(status).toContain("Atkinson Hyperlegible Mono:loaded");
  for (const response of await Promise.all(loaded)) expect(response.status()).toBe(200);
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
