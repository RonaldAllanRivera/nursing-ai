// "Use the demo note" and "Try drafting again" against the mock API, at 375, 768 and 1280 px.
// The first draft is made to fail on purpose (the `failDraft` option); the new job then drafts
// like any other. Every screen is checked with axe and for sideways scroll.
import { expect, test } from "@playwright/test";
import {
  checkDialog,
  checkScreen,
  openPatient,
  pageStatus,
  setMockOptions,
  shot,
  tabTo,
} from "./helpers.ts";

const NOTE_URL = /\/notes\/[0-9a-f-]{36}$/;
const AGAIN = "Try drafting again";
const HINT = "To save a new note, change the text.";

test("by keyboard: the demo note fills the box, a hiccup is tried again, and the draft opens", async ({
  page,
}) => {
  await setMockOptions(page, { failDraft: "provider_error" });
  await openPatient(page);
  const box = page.getByLabel("Your note");

  // "Use the demo note" is a secondary button: it fills the box and moves the cursor there.
  const demo = page.getByRole("button", { name: "Use the demo note" });
  await expect(demo).toBeVisible();
  await checkScreen(page, { night: true });
  await tabTo(page, demo, 12);
  await page.keyboard.press("Enter");
  await expect(box).toBeFocused();
  await expect(box).toHaveValue(/hilo since 2am/);
  // Nothing is saved by it.
  await expect(
    page.getByText("No notes yet this shift. Write the first one in Your note."),
  ).toBeVisible();
  await shot(page, "demo-note");

  // Save: the draft fails in a way worth another try.
  const save = page.getByRole("button", { name: "Save note" });
  await tabTo(page, save, 12);
  await page.keyboard.press("Enter");
  const form = page.locator("form").filter({ has: box });
  const again = form.getByRole("button", { name: AGAIN });
  await expect(again).toBeVisible({ timeout: 8000 });
  await expect(form.getByRole("alert")).toContainText("The AI service didn't answer.");
  await expect(page.getByText(HINT)).toHaveCount(0);
  await checkScreen(page, { night: true });
  await shot(page, "try-again");

  // Try again by keyboard: the progress line, then the note.
  await tabTo(page, again, 12);
  await page.keyboard.press("Enter");
  await expect(pageStatus(page)).toHaveText(
    "Drafting your note. This usually takes a few seconds.",
  );
  await expect(page).toHaveURL(NOTE_URL, { timeout: 8000 });
  await expect(page.getByRole("heading", { name: "Your note" })).toBeVisible();
  await checkScreen(page);
});

test("a typed note is only replaced after a question, and a failure that repeats offers no retry", async ({
  page,
}) => {
  await setMockOptions(page, { failDraft: "model_refused" });
  await openPatient(page);
  const box = page.getByLabel("Your note");
  await box.fill("my own words");
  await page.getByRole("button", { name: "Use the demo note" }).click();
  const dialog = page.getByRole("dialog", { name: "Replace what you typed?" });
  await expect(dialog).toBeVisible();
  // The safe choice has the cursor.
  await expect(dialog.getByRole("button", { name: "Keep my note" })).toBeFocused();
  await checkDialog(page);
  await shot(page, "replace-question");
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(box).toHaveValue("my own words");
  await expect(box).toBeFocused();

  await page.getByRole("button", { name: "Use the demo note" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Replace my note" }).click();
  await expect(box).toHaveValue(/hilo since 2am/);
  await expect(box).toBeFocused();

  // The AI declined: the same text would be declined again, so there is no button to try again.
  await page.getByRole("button", { name: "Save note" }).click();
  await expect(page.getByText(HINT)).toBeVisible({ timeout: 8000 });
  await expect(page.getByRole("button", { name: AGAIN })).toHaveCount(0);
  await checkScreen(page);
});

test("the shift list offers Try drafting again on a row, says Drafting, then offers the draft", async ({
  page,
}) => {
  await setMockOptions(page, { failDraft: "invalid_output" });
  await openPatient(page);
  await page.getByLabel("Your note").fill("pt c/o hilo since 2am, BP 90/60 HR 112");
  await page.getByRole("button", { name: "Save note" }).click();
  const list = page.getByRole("region", { name: "Notes this shift" });
  const rowButton = list.getByRole("button", { name: AGAIN });
  await expect(rowButton).toBeVisible({ timeout: 8000 });
  await expect(list).toContainText("wasn't kept. Your note is saved.");
  await checkScreen(page, { night: true });
  await shot(page, "row-try-again");

  // She has gone on to other words, so the form leaves this draft to the list.
  await page.getByLabel("Your note").fill("next note, not saved yet");

  await rowButton.click();
  await expect(list.getByText("Drafting")).toBeVisible();
  await expect(rowButton).toHaveCount(0);
  await expect(list.getByRole("link", { name: "Draft ready" })).toBeVisible({ timeout: 10000 });
  await checkScreen(page);
});

test("a draft started from the shift list is followed by the form that saved the note", async ({
  page,
}) => {
  await setMockOptions(page, { failDraft: "provider_error" });
  await openPatient(page);
  await page.getByLabel("Your note").fill("pt c/o hilo since 2am, BP 90/60 HR 112");
  await page.getByRole("button", { name: "Save note" }).click();
  const list = page.getByRole("region", { name: "Notes this shift" });
  await expect(list.getByRole("button", { name: AGAIN })).toBeVisible({ timeout: 8000 });
  await list.getByRole("button", { name: AGAIN }).click();
  // The row takes the focus the button leaves, and the form follows the same draft to its note.
  await expect(list.getByRole("listitem").first()).toBeFocused();
  await expect(page).toHaveURL(NOTE_URL, { timeout: 8000 });
});
