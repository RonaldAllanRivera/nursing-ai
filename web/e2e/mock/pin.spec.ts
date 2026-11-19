// The PIN screens against the mock API at 375, 768 and 1280 px: enter (a demo person, by keyboard,
// with a wrong try and the last-try warning), set (typed twice) and locked (a Google user), each
// checked with axe in the day and night themes and for sideways scroll.
import { expect, test, type Page } from "@playwright/test";
import {
  DEMO_PIN,
  SARAH,
  checkScreen,
  noSidewaysScroll,
  setMockOptions,
  shot,
  shotNight,
  tabTo,
} from "./helpers.ts";

const HEAD = "hana.reyes@example.com";
const INVITED = "irene.lim@example.com";
const LOCKED = "lito.santos@example.com";

/** `count` wrong PINs in a row. The field is read-only while a try is out, so `fill` waits for the answer by itself. */
async function wrongTries(page: Page, count: number) {
  const field = page.getByLabel("PIN", { exact: true });
  for (let n = 1; n <= count; n++) {
    await field.fill("999999");
    await page.keyboard.press("Enter");
  }
  await expect(page.getByRole("alert")).toContainText(`${String(5 - count)} try left`);
}

test("a demo person enters the PIN by keyboard; a wrong one counts and empties the field", async ({
  page,
}) => {
  await page.goto("/sign-in");
  await tabTo(page, page.getByRole("button", { name: SARAH }), 10);
  await page.keyboard.press("Enter");

  await expect(
    page.getByRole("heading", { name: "Enter your PIN, Sarah Navarro, RN" }),
  ).toBeVisible();
  await expect(page.getByText(`Demo PIN: ${DEMO_PIN}`)).toBeVisible();
  // The field is described by the hint, as every other PIN prompt's is.
  await expect(page.getByLabel("PIN", { exact: true })).toHaveAccessibleDescription(
    new RegExp(`Demo PIN: ${DEMO_PIN}`),
  );
  // No patient anywhere on the page.
  await expect(page.getByText(/Demo patient/)).toHaveCount(0);
  const field = page.getByLabel("PIN", { exact: true });
  await expect(field).toBeFocused();
  await checkScreen(page, { night: true });
  await shot(page, "pin-enter");
  await shotNight(page, "pin-enter");

  // The axe check used the theme toggle, so the cursor goes back to the field.
  await field.focus();
  await page.keyboard.type("999999");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("alert")).toHaveText("Wrong PIN. 4 tries left.");
  await expect(field).toHaveValue("");
  await expect(field).toBeFocused();
  await checkScreen(page);
  await shot(page, "pin-wrong");

  for (const left of [3, 2, 1]) {
    await page.keyboard.type("999999");
    await page.keyboard.press("Enter");
    await expect(page.getByRole("alert")).toContainText(
      `${String(left)} ${left === 1 ? "try" : "tries"} left`,
    );
  }
  await expect(page.getByRole("alert")).toHaveText(
    "Wrong PIN. 1 try left. Another wrong PIN ends this demo session.",
  );
  await checkScreen(page);
  await shot(page, "pin-last-try");

  await page.keyboard.type(DEMO_PIN);
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Patients on this ward" })).toBeVisible();
  await noSidewaysScroll(page);
});

test("the fifth wrong PIN ends a demo session and the sign-in screen says why", async ({
  page,
}) => {
  await page.goto("/sign-in");
  await page.getByRole("button", { name: SARAH }).click();
  const field = page.getByLabel("PIN", { exact: true });
  await wrongTries(page, 4);
  await field.fill("999999");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await expect(page.getByRole("alert")).toHaveText(
    "That was the fifth wrong PIN, so the demo session ended. Choose a person to start again.",
  );
  await expect(page).toHaveURL(/\/sign-in$/);
  await checkScreen(page);
  await shot(page, "pin-demo-ended");
});

test("a new Google user chooses a PIN typed twice", async ({ page }) => {
  await setMockOptions(page, { account: { user: INVITED } });
  await page.goto("/patients");
  await expect(page.getByRole("heading", { name: /^Choose a PIN, / })).toBeVisible();
  await expect(page.getByText(/Demo PIN/)).toHaveCount(0);
  await expect(page.getByLabel("New PIN")).toBeFocused();
  await checkScreen(page, { night: true });
  await shot(page, "pin-set");

  await page.keyboard.type("135792");
  await page.keyboard.press("Tab");
  await page.keyboard.type("135793");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("alert")).toHaveText("The two PINs don't match.");
  await checkScreen(page);
  await shot(page, "pin-set-mismatch");

  await page.getByLabel("New PIN").fill("111111");
  await page.getByLabel("Type it again").fill("111111");
  await page.keyboard.press("Enter");
  // The mock answers in the server's words ("that PIN is too easy"); the screen says it in its own.
  await expect(page.getByRole("alert")).toHaveText(
    "Choose a PIN that isn't one digit repeated or a run like 123456.",
  );
  await checkScreen(page);
  await shot(page, "pin-set-weak");

  await page.getByLabel("New PIN").fill("135792");
  await page.getByLabel("Type it again").fill("135792");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Patients on this ward" })).toBeVisible();
});

test("a locked PIN says who can reset it and offers nothing to type", async ({ page }) => {
  await setMockOptions(page, { account: { user: LOCKED } });
  await page.goto("/patients");
  await expect(
    page.getByText("Your PIN is locked. Ask a head nurse or the admin to reset it."),
  ).toBeVisible();
  await expect(page.getByRole("textbox")).toHaveCount(0);
  await expect(page.getByLabel("PIN", { exact: true })).toHaveCount(0);
  await expect(page.getByText(/Demo patient/)).toHaveCount(0);
  await checkScreen(page, { night: true });
  await shot(page, "pin-locked");
});

test("a Google user's fifth wrong PIN locks it", async ({ page }) => {
  await setMockOptions(page, { account: { user: HEAD } });
  await page.goto("/patients");
  const field = page.getByLabel("PIN", { exact: true });
  await expect(field).toBeFocused();
  await wrongTries(page, 4);
  await field.fill("999999");
  await page.keyboard.press("Enter");
  await expect(page.getByText(/^Your PIN is locked\./)).toBeVisible();
  await expect(field).toHaveCount(0);
  await noSidewaysScroll(page);
});
