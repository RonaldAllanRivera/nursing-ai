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
  expectNoViolations,
  isSmall,
  line,
  noSidewaysScroll,
  signInAs,
  tabTo,
} from "../mock/helpers.ts";

import { SARAH, card, isSmall, signInAs, tabTo } from "../mock/helpers.ts";

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

/** Press the screen's own action for a line that needs her: use the note's numbers, else confirm, else remove. */
async function actOn(page: Page, via: "pointer" | "keyboard") {
  const target = needing(page).first();
  const pickAction = async (): Promise<Locator> => {
    const options = [
      card(page).getByRole("button", { name: /^Use .* from your note$/ }),
      card(page).getByRole("button", { name: "Use the numbers from your note" }),
      card(page).getByRole("button", { name: "Wording is right" }),
      card(page).getByRole("button", { name: "Remove line" }),
    ];
    // The card fills in a moment after the tap: wait for any one of the actions.
    await expect
      .poll(
        async () => {
          for (const option of options) if ((await option.count()) > 0) return true;
          return false;
        },
        { message: "the card offers no action that resolves this line" },
      )
      .toBe(true);
    for (const option of options) if ((await option.count()) > 0) return option.first();
    throw new Error("unreachable");
  };
  // A line that is already selected (the source check left one) would toggle off on another tap.
  if ((await target.getAttribute("aria-current")) !== "true") {
    if (via === "keyboard") {
      await tabTo(page, target);
      await page.keyboard.press("Enter");
    } else {
      await target.click();
    }
  }
  await expect(card(page)).toBeVisible();
  const action = await pickAction();
  if (via === "keyboard") {
    await tabTo(page, action);
    await page.keyboard.press("Enter");
  } else {
    await action.click();
  }
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
  const target = draftLines(page).filter({ hasNotText: "Removed by you" }).first();
  if (via === "keyboard") {
    await tabTo(page, target);
    await page.keyboard.press("Enter");
    await tabTo(page, card(page).getByRole("button", { name: "Edit line" }));
    await page.keyboard.press("Enter");
  } else {
    await target.click();
    await card(page).getByRole("button", { name: "Edit line" }).click();
  }
  const box = page.getByRole("textbox", { name: "Edit line" });
  await expect(box).toBeFocused();
  const before = await box.inputValue();
  // Plain words, no digits: an edit must not add a number the check could flag.
  await page.keyboard.press("ControlOrMeta+End");
  await page.keyboard.type(" Checked at the bedside.");
  await expect(box).toHaveValue(`${before} Checked at the bedside.`);
  const save = page.getByRole("button", { name: "Save line" });
  if (via === "keyboard") {
    await tabTo(page, save);
    await page.keyboard.press("Enter");
  } else {
    await save.click();
  }
  await expect(box).toHaveCount(0);
  await expect(draftLines(page).filter({ hasText: "Edited by you" }).first()).toBeVisible();
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
