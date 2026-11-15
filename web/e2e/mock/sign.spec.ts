// Discarding a draft against the mock API, at 375, 768 and 1280 px. Resolving the three lines and
// signing, by pointer and by keyboard, are steps of the PH flow in journeys.spec.ts. The mock keeps
// its state in the page, so the note is reached the way a nurse reaches it (a full reload would
// sign the mock out).
import { expect, test } from "@playwright/test";
import { expectNoViolations, noSidewaysScroll, openDemoNote } from "./helpers.ts";

test("asks before it discards, and the discarded note has no actions", async ({ page }) => {
  await openDemoNote(page);
  await page.getByRole("button", { name: "Discard draft" }).click();
  const dialog = page.getByRole("dialog", { name: "Discard this draft?" });
  await expect(
    dialog.getByText("It won't reach the record. Your typed note stays saved."),
  ).toBeVisible();
  await expectNoViolations(page);
  await expect(dialog.getByRole("button", { name: "Keep draft" })).toBeFocused();
  await dialog.getByRole("button", { name: "Keep draft" }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByText("3 lines need you before you sign.")).toBeVisible();

  await page.getByRole("button", { name: "Discard draft" }).click();
  await dialog.getByRole("button", { name: "Discard draft" }).click();
  await expect(page.getByText("Discarded. This draft won't reach the record.")).toBeVisible();
  await expect(page.getByRole("button", { name: /Sign note|Discard draft/ })).toHaveCount(0);
  await expectNoViolations(page);
  await noSidewaysScroll(page);
});
