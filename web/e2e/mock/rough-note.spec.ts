// The rough note's character counter against the mock API, at 375, 768 and 1280 px. Writing and
// saving a note is a step of the PH flow in journeys.spec.ts.
import { expect, test } from "@playwright/test";
import { noSidewaysScroll, openPatient } from "./helpers.ts";

test("shows how many characters are left near the limit, without sideways scroll", async ({
  page,
}) => {
  await openPatient(page);
  await page.getByLabel("Your note").fill("a".repeat(3900));
  await expect(page.getByText("100 characters left")).toBeVisible();
  await noSidewaysScroll(page);
});
