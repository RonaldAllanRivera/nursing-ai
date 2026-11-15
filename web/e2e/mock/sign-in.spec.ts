// Sign-in, the header and the patient list against the mock API, at 375, 768 and 1280 px.
// The mock keeps its state in the page, so every flow navigates inside the app (no reload).
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

async function signInAsSarah(page: Page) {
  await page.goto("/sign-in");
  await page.getByRole("button", { name: SARAH }).click();
  await expect(page.getByRole("heading", { name: "Patients on this ward" })).toBeVisible();
}

test("signs in as the PH staff nurse and shows the header and the list", async ({ page }) => {
  await signInAsSarah(page);
  const header = page.getByRole("banner");
  await expect(header.getByText("Sarah Navarro, RN")).toBeVisible();
  await expect(header.getByText("Staff nurse")).toBeVisible();
  await expect(header.getByText("Shift 10-6")).toBeVisible();
  await expect(header.getByRole("button", { name: "Change shift" })).toBeVisible();
  await expect(header.getByRole("button", { name: "Night theme" })).toBeVisible();
  await expect(header.getByRole("button", { name: "Sign out" })).toBeVisible();
  await expect(page.getByText("22:00 11 Nov to 06:00 12 Nov 2026")).toBeVisible();
  await expect(page.getByRole("link", { name: /Demo patient A/ })).toBeVisible();
  await noSidewaysScroll(page);
});

test("changes the shift from the header, with the picker open, without sideways scroll", async ({
  page,
}) => {
  await signInAsSarah(page);
  await page.getByRole("button", { name: "Change shift" }).click();
  await expect(page.getByRole("button", { name: /^2-10/ })).toBeVisible();
  await noSidewaysScroll(page);
  await page.getByRole("button", { name: /^2-10/ }).click();
  await expect(page.getByText("Shift 2-10")).toBeVisible();
  await expect(page.getByText("14:00 to 22:00 11 Nov 2026")).toBeVisible();
});

test("works by keyboard: Tab to the persona, Enter, Tab to a patient row", async ({ page }) => {
  await page.goto("/sign-in");
  const sarah = page.getByRole("button", { name: SARAH });
  await expect(sarah).toBeVisible();
  for (let i = 0; i < 10; i++) {
    await page.keyboard.press("Tab");
    if (await sarah.evaluate((el) => el === document.activeElement)) break;
  }
  await expect(sarah).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Patients on this ward" })).toBeVisible();
  const row = page.getByRole("link", { name: /Demo patient A/ });
  for (let i = 0; i < 12; i++) {
    await page.keyboard.press("Tab");
    if (await row.evaluate((el) => el === document.activeElement)) break;
  }
  await expect(row).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Demo patient A" })).toBeVisible();
});

test("sign-in has no axe violations and fits", async ({ page }) => {
  await page.goto("/sign-in");
  await expect(page.getByRole("button", { name: SARAH })).toBeVisible();
  const results = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  expect(results.violations).toEqual([]);
  await noSidewaysScroll(page);
});

test("the patient list has no axe violations, in day and in night", async ({ page }) => {
  await signInAsSarah(page);
  await expect(page.getByRole("link", { name: /Demo patient A/ })).toBeVisible();
  const day = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  expect(day.violations).toEqual([]);
  await page.getByRole("button", { name: "Night theme" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "night");
  const night = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  expect(night.violations).toEqual([]);
});

test("the admin sees Settings only", async ({ page }) => {
  await page.goto("/sign-in");
  await page.getByRole("button", { name: "Admin · Victor Lazaro" }).click();
  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
  const header = page.getByRole("banner");
  await expect(header.getByText("Admin")).toBeVisible();
  await expect(header.getByRole("link", { name: "Patients" })).toHaveCount(0);
  await expect(header.getByRole("button", { name: "Change shift" })).toHaveCount(0);
  await noSidewaysScroll(page);
});
