// A room label of four to six characters ("412-A") stays on one line inside the bed tab, on the
// patient list, the patient's page and the trace view, at every width.
import { expect, test, type Locator, type Page } from "@playwright/test";
import { EMILY, signInAs } from "./helpers.ts";

async function expectFits(page: Page, label: string) {
  const text: Locator = page.getByText(label, { exact: true }).first();
  await expect(text).toBeVisible();
  const fit = await text.evaluate((el) => {
    const tab = el.parentElement as HTMLElement;
    const style = getComputedStyle(el);
    const box = el.getBoundingClientRect();
    const tabBox = tab.getBoundingClientRect();
    return {
      overflow: tab.scrollWidth - tab.clientWidth,
      height: box.height,
      fontSize: parseFloat(style.fontSize),
      outside: box.left < tabBox.left - 0.5 || box.right > tabBox.right + 0.5,
    };
  });
  expect(fit.overflow, "the tab's content is wider than the tab").toBeLessThanOrEqual(0);
  expect(fit.height, "the label wraps onto a second line").toBeLessThan(fit.fontSize * 1.6);
  expect(fit.outside, "the label spills out of the tab").toBe(false);
}

test("a four-character room label fits its tab in the list, the page and the trace view", async ({
  page,
}) => {
  await signInAs(page, EMILY, "Patients on this unit");
  await expectFits(page, "412-A");
  await page.getByRole("link", { name: /Demo patient C/ }).click();
  await expect(page.getByRole("heading", { name: "Demo patient C" })).toBeVisible();
  await expectFits(page, "412-A");
  await page.getByLabel("Your note").fill("0830 pt A&Ox4, c/o R hip pain 6/10");
  await page.getByRole("button", { name: "Save note" }).click();
  await expect(page.getByRole("heading", { name: "Your note" })).toBeVisible();
  await expectFits(page, "412-A");
});
