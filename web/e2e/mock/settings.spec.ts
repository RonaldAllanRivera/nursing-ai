// The admin's Settings screen against the mock API, at 375, 768 and 1280 px.
// The mock keeps its state in the page, so every flow navigates inside the app (no reload).
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Locator, type Page } from "@playwright/test";

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

async function noSidewaysScroll(page: Page) {
  const fits = await page.evaluate(
    () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
  );
  expect(fits).toBe(true);
}

async function openSettings(page: Page) {
  await page.goto("/sign-in");
  await page.getByRole("button", { name: "Admin · Victor Lazaro" }).click();
  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Facility name" })).toHaveValue(
    "SYNTHETIC Demo Hospital (PH)",
  );
}

/** Tab until `target` has the focus (a keyboard user's path), failing if it never does. */
async function tabTo(page: Page, target: Locator, limit = 80) {
  for (let i = 0; i < limit; i++) {
    await page.keyboard.press("Tab");
    if (await target.evaluate((el) => el === document.activeElement)) return;
  }
  throw new Error("The keyboard never reached the field.");
}

async function expectNoViolations(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  expect(results.violations).toEqual([]);
}

test("shows the facility's settings and fits the screen", async ({ page }) => {
  await openSettings(page);
  await expect(page.getByText("Changes apply to new notes.")).toBeVisible();
  await expect(page.getByRole("group", { name: "Shift 3" })).toBeVisible();
  await expect(page.getByRole("radio", { name: "Red" }).last()).toBeChecked();
  await noSidewaysScroll(page);
  await expectNoViolations(page);
});

test("the admin edits a label by keyboard only and saves", async ({ page }) => {
  await openSettings(page);
  const label = page.getByRole("group", { name: "Shift 3" }).getByLabel("Label");
  await tabTo(page, label);
  await page.keyboard.press("ControlOrMeta+a");
  await page.keyboard.type("Night");
  await tabTo(page, page.getByRole("button", { name: "Save settings" }));
  await page.keyboard.press("Enter");
  await expect(page.getByRole("status")).toContainText("Saved.");
  await expect(label).toHaveValue("Night");
  await noSidewaysScroll(page);
});

test("a nurse who signs in after the save sees the new label", async ({ page }) => {
  await openSettings(page);
  const label = page.getByRole("group", { name: "Shift 3" }).getByLabel("Label");
  await label.fill("Night");
  await page.getByRole("button", { name: "Save settings" }).click();
  await expect(page.getByRole("status")).toContainText("Saved.");
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.getByRole("button", { name: "Staff nurse · Sarah Navarro, RN" }).click();
  await expect(page.getByRole("banner").getByText("Shift Night")).toBeVisible();
});

test("a gap shows above the shifts before Save, and the page is still accessible", async ({
  page,
}) => {
  await openSettings(page);
  await page.getByRole("group", { name: "Shift 2" }).getByLabel("Starts").fill("15:00");
  await expect(page.getByText("There's a gap between 14:00 and 15:00.")).toBeVisible();
  await page.getByRole("button", { name: "Save settings" }).click();
  await expect(page.getByRole("status")).not.toContainText("Saved.");
  await noSidewaysScroll(page);
  await expectNoViolations(page);
});

test("a field error from the form is tied to its field, and the page is accessible", async ({
  page,
}) => {
  await openSettings(page);
  const name = page.getByRole("textbox", { name: "Facility name" });
  await name.fill("");
  await page.getByRole("button", { name: "Save settings" }).click();
  await expect(name).toBeFocused();
  await expect(name).toHaveAttribute("aria-invalid", "true");
  await expect(name).toHaveAccessibleDescription("Enter the facility's name.");
  await noSidewaysScroll(page);
  await expectNoViolations(page);
});

test("a server error lands on its field", async ({ page }) => {
  await openSettings(page);
  // The form checks what the server checks, so to see the server's answer the request is
  // answered here, in the page, before it reaches the mock.
  await page.evaluate(() => {
    const original = window.fetch.bind(window);
    window.fetch = (input, init) => {
      const request = new Request(input, init);
      if (request.method !== "PUT") return original(input, init);
      return Promise.resolve(
        new Response(
          JSON.stringify({
            type: "about:blank",
            title: "The request isn't valid",
            status: 422,
            code: "invalid_request",
            errors: [{ field: "body.shifts.1.label", message: "A label is 1 to 40 characters." }],
          }),
          { status: 422, headers: { "Content-Type": "application/problem+json" } },
        ),
      );
    };
  });
  await page.getByRole("button", { name: "Save settings" }).click();
  const label = page.getByRole("group", { name: "Shift 2" }).getByLabel("Label");
  await expect(label).toBeFocused();
  await expect(label).toHaveAccessibleDescription("A label is 1 to 40 characters.");
  await noSidewaysScroll(page);
  await expectNoViolations(page);
});

test("asks before switching facility with unsaved changes, with the dialog accessible", async ({
  page,
}) => {
  await openSettings(page);
  await page.getByRole("textbox", { name: "Facility name" }).fill("SYNTHETIC Changed");
  await page.getByRole("combobox", { name: "Facility" }).selectOption("us-demo");
  const dialog = page.getByRole("dialog", { name: "Discard your changes?" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Keep editing" })).toBeFocused();
  await expectNoViolations(page);
  await page.keyboard.press("Tab");
  await expect(dialog.getByRole("button", { name: "Discard changes" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("textbox", { name: "Facility name" })).toHaveValue(
    "SYNTHETIC Demo Hospital (US)",
  );
  await noSidewaysScroll(page);
});

test("adds and removes a shift row without sideways scroll", async ({ page }) => {
  await openSettings(page);
  await page.getByRole("button", { name: "Add a shift" }).click();
  await expect(page.getByRole("group", { name: "Shift 4" })).toBeVisible();
  await noSidewaysScroll(page);
  await page.getByRole("button", { name: "Remove shift 2-10" }).click();
  await expect(page.getByRole("group", { name: "Shift 4" })).toHaveCount(0);
});
