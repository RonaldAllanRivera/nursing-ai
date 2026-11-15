// The sign-in page's fonts against the mock API, at 375, 768 and 1280 px (see
// playwright.mock.config.ts). Its axe and fit checks are the first step of the PH flow in
// journeys.spec.ts.
import { expect, test } from "@playwright/test";

test("loads the sign-in page with its fonts", async ({ page }) => {
  const fonts = ["AtkinsonHyperlegibleNext-latin.woff2", "AtkinsonHyperlegibleMono-latin.woff2"];
  const loaded = fonts.map((file) =>
    page.waitForResponse((response) => response.url().endsWith(`/fonts/${file}`)),
  );
  await page.goto("/sign-in");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await expect(page.getByText(/^API:/)).toHaveText("API: healthy");
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
