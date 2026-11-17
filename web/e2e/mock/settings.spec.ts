// The admin's Settings screen against the mock API, at 375, 768 and 1280 px. The admin path in
// journeys.spec.ts (375 and 1280 px) walks the rename, the US shifts and the nurse's new label.
// The mock keeps its state in the page, so every flow navigates inside the app (no reload).
import { expect, test, type Page } from "@playwright/test";
import {
  ADMIN,
  enterDemoPin,
  enterPinInDialog,
  SAVE_PIN_DIALOG,
  shot,
  SARAH,
  expectHeaderAtMostTwoRows,
  checkDialog,
  checkScreen,
  expectNoViolations,
  noSidewaysScroll,
  pageStatus,
  signInAs,
  tabTo,
} from "./helpers.ts";

async function openSettings(page: Page) {
  await signInAs(page, ADMIN, "Settings");
  await expect(page.getByRole("textbox", { name: "Facility name" })).toHaveValue(
    "SYNTHETIC Demo Hospital (PH)",
  );
}

test("shows the facility's settings and fits the screen", async ({ page }) => {
  await openSettings(page);
  // The admin's header, at every width: the Admin pill, no Patients link, no shift control.
  const header = page.getByRole("banner");
  await expect(header.getByText("Admin")).toBeVisible();
  await expect(header.getByRole("link", { name: "Patients" })).toHaveCount(0);
  await expect(header.getByRole("button", { name: "Change shift" })).toHaveCount(0);
  await expectHeaderAtMostTwoRows(page);
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
  await enterPinInDialog(page, SAVE_PIN_DIALOG);
  await expect(pageStatus(page)).toContainText("Saved.");
  await expect(label).toHaveValue("Night");
  // The focus is back on the button that opened the question.
  await expect(page.getByRole("button", { name: "Save settings" })).toBeFocused();
  await noSidewaysScroll(page);
});

test("a nurse who signs in after the save sees the new label", async ({ page }) => {
  await openSettings(page);
  const label = page.getByRole("group", { name: "Shift 3" }).getByLabel("Label");
  await label.fill("Night");
  await page.getByRole("button", { name: "Save settings" }).click();
  await enterPinInDialog(page, SAVE_PIN_DIALOG);
  await expect(pageStatus(page)).toContainText("Saved.");
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.getByRole("button", { name: SARAH }).click();
  await enterDemoPin(page);
  await expect(page.getByRole("banner").getByText("Shift Night")).toBeVisible();
});

test("a gap shows above the shifts before Save, and the page is still accessible", async ({
  page,
}) => {
  await openSettings(page);
  await page.getByRole("group", { name: "Shift 2" }).getByLabel("Starts").fill("15:00");
  await expect(page.getByText("There's a gap between 14:00 and 15:00.")).toBeVisible();
  await page.getByRole("button", { name: "Save settings" }).click();
  // Save found the problem and sent nothing: the problems block has the focus, and nothing is saved.
  await expect(page.locator("#shift-problems")).toBeFocused();
  await expect(pageStatus(page)).not.toContainText("Saved.");
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
  await enterPinInDialog(page, SAVE_PIN_DIALOG);
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

test("saving asks for the PIN: a wrong one keeps the form, and the dialog is accessible day and night", async ({
  page,
}) => {
  await openSettings(page);
  const name = page.getByRole("textbox", { name: "Facility name" });
  await name.fill("SYNTHETIC Edited Name");
  await tabTo(page, page.getByRole("button", { name: "Save settings" }));
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: SAVE_PIN_DIALOG });
  await expect(dialog.getByLabel("Your PIN")).toBeFocused();
  await shot(page, "settings-pin");
  await checkDialog(page);
  // Fewer than six digits: said, nothing sent.
  await page.keyboard.type("1234");
  await page.keyboard.press("Enter");
  await expect(dialog.getByText("Enter your 6-digit PIN.")).toBeVisible();
  // A wrong PIN: the tries left, an empty field with the cursor in it, and the form untouched.
  await page.keyboard.press("ControlOrMeta+a");
  await page.keyboard.type("999999");
  await page.keyboard.press("Enter");
  await expect(dialog.getByText("Wrong PIN. 4 tries left.")).toBeVisible();
  await expect(dialog.getByLabel("Your PIN")).toHaveValue("");
  await expect(dialog.getByLabel("Your PIN")).toBeFocused();
  await shot(page, "settings-pin-wrong");
  await checkScreen(page);
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(name).toHaveValue("SYNTHETIC Edited Name");
  await expect(pageStatus(page)).not.toContainText("Saved.");
});

test("the admin sets how long nurses stay signed in", async ({ page }) => {
  await openSettings(page);
  const hours = page.getByLabel("Sign nurses out after (hours)");
  await expect(hours).toHaveValue("12");
  await expect(page.getByText("Applies to sessions that start after you save.")).toBeVisible();
  await tabTo(page, hours);
  await page.keyboard.press("ControlOrMeta+a");
  await page.keyboard.type("25");
  await page.keyboard.press("Enter");
  // Refused before any PIN is asked for.
  await expect(hours).toHaveAccessibleDescription(/Enter 1 to 24 hours\./);
  await expect(hours).toBeFocused();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await checkScreen(page, { night: true });
  await tabTo(page, hours);
  await page.keyboard.press("ControlOrMeta+a");
  await page.keyboard.type("10");
  await page.keyboard.press("Enter");
  await enterPinInDialog(page, SAVE_PIN_DIALOG);
  await expect(pageStatus(page)).toContainText("Saved.");
  await expect(hours).toHaveValue("10");
  await shot(page, "settings-hours");
  await noSidewaysScroll(page);
});

test("the demo's admin puts the settings back to how the demo started", async ({ page }) => {
  await openSettings(page);
  const name = page.getByRole("textbox", { name: "Facility name" });
  await name.fill("SYNTHETIC Edited Name");
  await tabTo(page, page.getByRole("button", { name: "Save settings" }));
  await page.keyboard.press("Enter");
  await enterPinInDialog(page, SAVE_PIN_DIALOG);
  await expect(pageStatus(page)).toContainText("Saved.");

  await tabTo(page, page.getByRole("button", { name: "Reset demo settings" }));
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "Reset demo settings" });
  await expect(
    dialog.getByText("Put this facility's settings back to how the demo started?"),
  ).toBeVisible();
  await shot(page, "settings-reset");
  await checkDialog(page);
  await enterPinInDialog(page, "Reset demo settings");
  await expect(pageStatus(page)).toContainText("Settings are back to how the demo started.");
  await expect(name).toHaveValue("SYNTHETIC Demo Hospital (PH)");
  await expect(page.getByRole("button", { name: "Reset demo settings" })).toBeFocused();
  await shot(page, "settings-reset-done");
  await checkScreen(page);
});
