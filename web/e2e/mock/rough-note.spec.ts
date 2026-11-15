// Writing a rough note for demo patient A against the mock API, at 375, 768 and 1280 px.
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

async function openPatientA(page: Page) {
  await page.goto("/sign-in");
  await page.getByRole("button", { name: SARAH }).click();
  await page.getByRole("link", { name: /Demo patient A/ }).click();
  await expect(page.getByRole("heading", { name: "Demo patient A" })).toBeVisible();
}

test("the patient page shows the bed tab, the shift and the empty notes list", async ({ page }) => {
  await openPatientA(page);
  const main = page.getByRole("main");
  await expect(main.getByText("Bed", { exact: true })).toBeVisible();
  await expect(main.getByText("Synthetic")).toBeVisible();
  await expect(main.getByText("64 F, Medical Ward")).toBeVisible();
  await expect(main.getByText("22:00 11 Nov to 06:00 12 Nov 2026")).toBeVisible();
  await expect(main.getByText("No notes yet this shift. Write the first one below.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Save note" })).toBeDisabled();
  await noSidewaysScroll(page);
});

test("types a note, saves it and lands on the note", async ({ page }) => {
  await openPatientA(page);
  await page.getByLabel("Your note").fill("pt c/o hilo since 2am, BP 130/80, given paracetamol");
  await page.getByRole("button", { name: "Save note" }).click();
  await expect(
    page.getByText("Drafting your note. This usually takes a few seconds."),
  ).toBeVisible();
  await expect(page).toHaveURL(/\/notes\/[0-9a-f-]{36}$/, { timeout: 8000 });
  await expect(page.getByRole("heading", { name: /^Note / })).toBeVisible();
  await noSidewaysScroll(page);
});

test("works by keyboard: Tab to the note, type, Tab to Save note, Enter", async ({ page }) => {
  await openPatientA(page);
  const box = page.getByLabel("Your note");
  for (let i = 0; i < 12; i++) {
    await page.keyboard.press("Tab");
    if (await box.evaluate((el) => el === document.activeElement)) break;
  }
  await expect(box).toBeFocused();
  await page.keyboard.type("pt resting, no complaints");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Save note" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/notes\/[0-9a-f-]{36}$/, { timeout: 8000 });
});

test("the patient page has no axe violations, in day and in night, with text typed", async ({
  page,
}) => {
  await openPatientA(page);
  await page.getByLabel("Your note").fill("pt c/o hilo");
  const day = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  expect(day.violations).toEqual([]);
  await page.getByRole("button", { name: "Night theme" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "night");
  const night = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  expect(night.violations).toEqual([]);
});

test("shows how many characters are left near the limit, without sideways scroll", async ({
  page,
}) => {
  await openPatientA(page);
  await page.getByLabel("Your note").fill("a".repeat(3900));
  await expect(page.getByText("100 characters left")).toBeVisible();
  await noSidewaysScroll(page);
});
