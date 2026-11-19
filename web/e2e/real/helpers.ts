// Helpers for the journeys against the real stack. Nothing here depends on the draft's wording:
// in replay mode the draft is the live model's, and the database keeps its notes between runs.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, type Locator, type Page } from "@playwright/test";

export {
  ADMIN,
  EMILY,
  SARAH,
  card,
  checkScreen,
  enterDemoPin,
  enterPinInDialog,
  expectNoViolations,
  pageStatus,
  SAVE_PIN_DIALOG,
  isSmall,
  line,
  noSidewaysScroll,
  signInAs,
  tabTo,
} from "../mock/helpers.ts";

import { DEMO_PIN, SARAH, card, isSmall, signInAs, tabTo } from "../mock/helpers.ts";

/** The rough note of a demo case, typed exactly: a replay recording is keyed on this text. */
export function demoNoteText(caseId: "demo-1" | "demo-3"): string {
  const file = fileURLToPath(
    new URL(`../../../core/src/nursing_core/demo/cases/${caseId}.json`, import.meta.url),
  );
  const parsed: unknown = JSON.parse(readFileSync(file, "utf8"));
  const text = (parsed as { rough_note?: { text?: unknown } }).rough_note?.text;
  if (typeof text !== "string" || text === "") throw new Error(`${caseId} has no rough note text.`);
  return text;
}

export const NOTE_URL = /\/notes\/[0-9a-f-]{36}$/;
export const SIGNED_AT = /^Signed by you at \d\d:\d\d\.$/;
export const HASH = /^Note hash [0-9a-f]{12}$/;
/** What a line says while it still needs the nurse. */
const NEEDS_YOU = /Number differs|Not in your note|AI wording — check/;
/** The draft can take a while: the API's worker makes it in the background. */
export const DRAFT_WAIT = 90_000;

export const patientLink = (page: Page, name: string) =>
  page.getByRole("link", { name: new RegExp(name) });

export async function openPatient(
  page: Page,
  patient: string,
  persona = SARAH,
  landing = "Patients on this ward",
) {
  await signInAs(page, persona, landing);
  await patientLink(page, patient).click();
  await expect(page.getByRole("heading", { name: patient })).toBeVisible();
}

/** Type the note (or press its keys), save, and wait for the trace view of the new draft. */
export async function saveNote(page: Page, text: string, opts: { keyboard?: boolean } = {}) {
  const box = page.getByLabel("Your note");
  if (opts.keyboard) await page.keyboard.type(text);
  else await box.fill(text);
  await expect(box).toHaveValue(text);
  const save = page.getByRole("button", { name: "Save note" });
  if (opts.keyboard) {
    await page.keyboard.press("Tab");
    await expect(save).toBeFocused();
    await page.keyboard.press("Enter");
  } else {
    await save.click();
  }
  await expect(page).toHaveURL(NOTE_URL, { timeout: DRAFT_WAIT });
  await expect(page.getByRole("heading", { name: "Your note" })).toBeVisible();
  await expect(draftLines(page).first()).toBeVisible();
}

/** The draft's lines: the buttons in the trace view's draft, not the card beside it. */
export const draftLines = (page: Page) =>
  page.locator("main").getByRole("button", {
    name: /Source found|Number differs|Not in your note|AI wording — check|Checked by you|Edited by you|Removed by you/,
  });

const needing = (page: Page) => draftLines(page).filter({ hasText: NEEDS_YOU });

/** Tap each line in turn: the words it came from light up in the note when it has a quote. */
export async function seeSourceHighlight(page: Page) {
  const count = await draftLines(page).count();
  let lit = 0;
  for (let i = 0; i < count; i++) {
    await draftLines(page).nth(i).click();
    await expect(card(page)).toBeVisible();
    const marks = page.locator(".note-text mark.hl");
    // Wait for the selection to settle: the URL names the line.
    await expect(page).toHaveURL(/\?line=/);
    if ((await marks.count()) > 0) {
      await expect(marks.first()).toBeVisible();
      await expect
        .poll(() => marks.first().evaluate((el) => getComputedStyle(el).backgroundImage))
        .toContain("linear-gradient");
      lit++;
      break;
    }
  }
  expect(lit, "no line lit up its source words in the note").toBeGreaterThan(0);
}

/**
 * Select a line, unless it is already selected: a second tap on the selected line closes the card
 * below 960 px.
 */
async function selectLine(page: Page, target: Locator, via: "pointer" | "keyboard") {
  if ((await target.getAttribute("aria-current")) !== "true") {
    if (via === "keyboard") {
      await tabTo(page, target);
      await page.keyboard.press("Enter");
    } else {
      await target.click();
    }
  }
  await expect(card(page)).toBeVisible();
}

async function press(page: Page, button: Locator, via: "pointer" | "keyboard") {
  if (via === "keyboard") {
    await tabTo(page, button);
    await page.keyboard.press("Enter");
  } else {
    await button.click();
  }
}

/** Open the card's edit box on the selected line, add plain words and save. */
async function editSelectedLine(page: Page, via: "pointer" | "keyboard") {
  await press(page, card(page).getByRole("button", { name: "Edit line" }), via);
  const box = page.getByRole("textbox", { name: "Edit line" });
  await expect(box).toBeFocused();
  const before = await box.inputValue();
  // Plain words, no digits: an edit must not add a number the check could flag.
  await page.keyboard.press("ControlOrMeta+End");
  await page.keyboard.type(" Checked at the bedside.");
  await expect(box).toHaveValue(`${before} Checked at the bedside.`);
  await press(page, page.getByRole("button", { name: "Save line" }), via);
  await expect(box).toHaveCount(0);
}

/**
 * Press the screen's own action for a line that needs her: use the note's numbers, else confirm,
 * else remove. A line that offers only Edit (a Focus line with no source, a number with none to
 * use) is edited instead.
 */
async function actOn(page: Page, via: "pointer" | "keyboard") {
  await selectLine(page, needing(page).first(), via);
  const options = [
    card(page).getByRole("button", { name: /^Use .* from your note$/ }),
    card(page).getByRole("button", { name: "Use the numbers from your note" }),
    card(page).getByRole("button", { name: "Wording is right" }),
    card(page).getByRole("button", { name: "Remove line" }),
    card(page).getByRole("button", { name: "Edit line" }),
  ];
  // The card fills in a moment after the tap: wait for any one of the actions.
  await expect
    .poll(
      async () => {
        for (const option of options) if ((await option.count()) > 0) return true;
        return false;
      },
      { message: "the card offers no action for this line" },
    )
    .toBe(true);
  for (const option of options.slice(0, -1)) {
    if ((await option.count()) > 0) return press(page, option.first(), via);
  }
  await editSelectedLine(page, via);
}

/** Resolve every line that blocks signing, whatever it is, until the bar says every line is checked. */
export async function resolveEveryLine(page: Page, via: "pointer" | "keyboard" = "pointer") {
  const done = page.getByText("Every line is checked.");
  for (let guard = 0; guard < 40; guard++) {
    const left = await needing(page).count();
    if (left === 0) break;
    await actOn(page, via);
    await expect(needing(page)).toHaveCount(left - 1, { timeout: 15_000 });
  }
  await expect(done).toBeVisible();
  await expect(needing(page)).toHaveCount(0);
}

/** Edit one line's text through the card: the first line she has not removed. */
export async function editOneLine(page: Page, via: "pointer" | "keyboard" = "pointer") {
  await selectLine(page, draftLines(page).filter({ hasNotText: "Removed by you" }).first(), via);
  await editSelectedLine(page, via);
  await expect(draftLines(page).filter({ hasText: "Edited by you" }).first()).toBeVisible();
}

/** ArrowDown then ArrowUp between draft lines: the selection and the focus follow. */
export async function walkLinesByArrows(page: Page) {
  const lines = draftLines(page);
  expect(await lines.count()).toBeGreaterThan(1);
  await selectLine(page, lines.first(), "keyboard");
  await expect(lines.first()).toHaveAttribute("aria-current", "true");
  await page.keyboard.press("ArrowDown");
  await expect(lines.nth(1)).toHaveAttribute("aria-current", "true");
  await expect(lines.nth(1)).toBeFocused();
  await expect(lines.first()).not.toHaveAttribute("aria-current", "true");
  await page.keyboard.press("ArrowUp");
  await expect(lines.first()).toHaveAttribute("aria-current", "true");
  await expect(lines.first()).toBeFocused();
}

/** Sign through the dialog; the caller may watch the response. Returns once the note is locked. */
export async function signNote(page: Page, via: "pointer" | "keyboard" = "pointer") {
  if (isSmall(page) && (await card(page).count()) > 0) {
    // On a small screen the drawer sits over the Sign bar: close it first, as the nurse would.
    await card(page).getByRole("button", { name: "Close" }).click();
  }
  const open = page.getByRole("button", { name: "Sign note" });
  if (via === "keyboard") {
    await tabTo(page, open);
    await page.keyboard.press("Enter");
  } else {
    await open.click();
  }
  const dialog = page.getByRole("dialog", { name: /^Sign this (FDAR|DAR) note$/ });
  await expect(dialog).toBeVisible();
  // It asks for her own PIN first, with the cursor already in the field.
  await expect(dialog.getByLabel("Your PIN")).toBeFocused();
  await page.keyboard.type(DEMO_PIN);
  const confirm = dialog.getByRole("button", { name: "Sign note" });
  const answered = page.waitForResponse(
    (r) =>
      r.request().method() === "POST" && /\/notes\/[^/]+\/sign$/.test(new URL(r.url()).pathname),
  );
  if (via === "keyboard") {
    await tabTo(page, confirm);
    await page.keyboard.press("Enter");
  } else {
    await confirm.click();
  }
  const response = await answered;
  await expect(dialog).toBeHidden();
  await expect(page.getByText(SIGNED_AT)).toBeVisible();
  await expect(page.getByText(HASH)).toBeVisible();
  await expect(page.getByText("Signed. This note is locked.")).toBeVisible();
  return response;
}

/** A throwaway e2e user made through the API's test-only route (APP_ENV=test): her cookie is the page's. */
export async function startTestSession(
  page: Page,
  who: { role: "staff_nurse" | "head_nurse" | "admin"; facilityKey: string | null; pin?: string },
) {
  const response = await page.request.post("/api/v1/test/session", {
    data: {
      role: who.role,
      facility_key: who.facilityKey,
      ...(who.pin === undefined ? {} : { pin: who.pin }),
    },
  });
  expect(response.status(), await response.text()).toBe(201);
}

/** Revoke every e2e user (no session needed). */
export async function tearDownTestUsers(page: Page) {
  const response = await page.request.post("/api/v1/test/teardown");
  expect(response.ok(), await response.text()).toBe(true);
}

/** A PIN no rule refuses: not one digit repeated, not a run. */
export const TEST_PIN = "246813";
