// The header's shift picker against the mock API, at 375, 768 and 1280 px. Sign-in, the header
// and the patient list are the first steps of the PH flow in journeys.spec.ts.
import { expect, test } from "@playwright/test";
import { noSidewaysScroll, signInAsSarah } from "./helpers.ts";

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
