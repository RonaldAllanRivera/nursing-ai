// The plan's three journeys against the mock API. Each starts from a fresh page and needs nothing
// from any other test. The mock keeps its state in the page, so every journey navigates inside the
// app (a full reload would sign the mock out).
//
//   1. The whole PH flow, at 375, 768 and 1280 px, by pointer and by keyboard alone.
//   2. The US path, at 375 px only (the other widths are skipped: the layout is the same screens,
//      so one width is enough to prove the region words, the shift and the Pacific times).
//   3. The admin path, at 375 and 1280 px (768 is skipped), by keyboard alone.
//
// Every screen of a journey is checked with axe (WCAG 2.2 AA) and for sideways scroll.
// Set E2E_SHOTS=<folder> to save a full-page screenshot of each screen.
import { expect, test } from "@playwright/test";
import { widths } from "../widths.ts";
import {
  ADMIN,
  D2,
  EMILY,
  FOCUS,
  PHYSICIAN,
  ROUGH_NOTE,
  SARAH,
  card,
  checkScreen,
  expectHeaderAtMostTwoRows,
  isSmall,
  line,
  noSidewaysScroll,
  resolveThreeLines,
  shot,
  signInAs,
  tabTo,
} from "./helpers.ts";

const SIGNED_AT = /^Signed by you at \d\d:\d\d\.$/;
const HASH = /^Note hash [0-9a-f]{12}$/;
const NOTE_URL = /\/notes\/[0-9a-f-]{36}$/;

// Project names come from widths.ts, so a rename there can't skip a journey everywhere.
const projectAt = (width: number) => {
  const found = widths.find((w) => w.width === width);
  if (!found) throw new Error(`No project at ${String(width)} px in widths.ts.`);
  return found.name;
};

test("PH flow: sign in, write a note, wait for the draft, check three lines, sign, see it locked", async ({
  page,
}) => {
  // Sign-in.
  await page.goto("/sign-in");
  await expect(page.getByRole("button", { name: SARAH })).toBeVisible();
  await checkScreen(page);
  await shot(page, "sign-in");

  // The patient list, with the header.
  await page.getByRole("button", { name: SARAH }).click();
  await expect(page.getByRole("heading", { name: "Patients on this ward" })).toBeVisible();
  const header = page.getByRole("banner");
  await expect(header.getByText("Sarah Navarro, RN")).toBeVisible();
  await expect(header.getByText("Staff nurse")).toBeVisible();
  await expect(header.getByText("Shift 10-6")).toBeVisible();
  await expectHeaderAtMostTwoRows(page);
  await expect(header.getByRole("button", { name: "Change shift" })).toBeVisible();
  await expect(header.getByRole("button", { name: "Night theme" })).toBeVisible();
  await expect(header.getByRole("button", { name: "Sign out" })).toBeVisible();
  await expect(page.getByText("22:00 11 Nov to 06:00 12 Nov 2026")).toBeVisible();
  await expect(page.getByRole("link", { name: /Demo patient A/ })).toBeVisible();
  await checkScreen(page, { night: true });
  await shot(page, "list");

  // The patient page, with a typed note.
  await page.getByRole("link", { name: /Demo patient A/ }).click();
  await expect(page.getByRole("heading", { name: "Demo patient A" })).toBeVisible();
  const main = page.getByRole("main");
  await expect(main.getByText("Bed", { exact: true })).toBeVisible();
  await expect(main.getByText("Synthetic")).toBeVisible();
  await expect(main.getByText("64 F, Medical Ward")).toBeVisible();
  await expect(main.getByText("22:00 11 Nov to 06:00 12 Nov 2026")).toBeVisible();
  await expect(
    main.getByText("No notes yet this shift. Write the first one in Your note."),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Save note" })).toBeDisabled();
  await page.getByLabel("Your note").fill(ROUGH_NOTE);
  await checkScreen(page, { night: true });
  await shot(page, "patient");

  // Save, wait for the draft.
  await page.getByRole("button", { name: "Save note" }).click();
  await expect(
    page.getByText("Drafting your note. This usually takes a few seconds."),
  ).toBeVisible();
  await shot(page, "drafting");
  await expect(page).toHaveURL(NOTE_URL, { timeout: 8000 });
  await expect(page.getByRole("heading", { name: "Your note" })).toBeVisible();

  // The trace view: the note, the draft and the answer.
  await expect(page.getByRole("heading", { name: /^Demo patient A/, level: 1 })).toBeVisible();
  await expect(
    page.getByText(
      "64 F, Medical Ward. FDAR note for the 10-6 shift, 22:00 11 Nov to 06:00 12 Nov 2026.",
    ),
  ).toBeVisible();
  await expect(page.getByText("Typed at 05:10. The AI never changes it.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "FDAR draft" })).toBeVisible();
  await expect(page.getByText("3 lines need you before you sign.")).toBeVisible();
  await expect(page.getByText("Not written — left empty")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Missing from this note" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign note" })).toBeVisible();
  await checkScreen(page);

  // Select a line: its words light up in the note, the differing number is marked.
  await line(page, D2).click();
  await expect(page).toHaveURL(/\?line=e1-D2$/);
  const mark = page.locator(".note-text mark.hl");
  await expect(mark).toHaveCount(1);
  await expect(mark).toHaveText("BP 90/60 HR 112");
  await expect(mark).toBeVisible();
  await expect(mark.locator(".num-bad")).toHaveText("112");
  // The highlight colour is painted (the highlighter's gradient), not just present in the markup.
  await expect
    .poll(() => mark.evaluate((el) => getComputedStyle(el).backgroundImage))
    .toContain("linear-gradient");
  const source = page.getByRole("complementary", { name: /came from/ });
  await expect(source.getByRole("heading", { name: "Number differs" })).toBeVisible();
  await expect(source.getByText("The draft says 121. Your note says 112.")).toBeVisible();
  await checkScreen(page, { night: true });
  await shot(page, "trace");

  // Resolve the three lines.
  await resolveThreeLines(page);
  await noSidewaysScroll(page);

  // Sign. On a small screen the drawer sits over the Sign bar: close it first, as the nurse would.
  if (isSmall(page)) await card(page).getByRole("button", { name: "Close" }).click();
  await page.getByRole("button", { name: "Sign note" }).click();
  const dialog = page.getByRole("dialog", { name: "Sign this FDAR note" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText("Not in this note:")).toBeVisible();
  await checkScreen(page);
  await shot(page, "sign-dialog");

  // Signed: locked, with its hash. The removed line is not in the record.
  await dialog.getByRole("button", { name: "Sign note" }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByText(SIGNED_AT)).toBeVisible();
  await expect(page.getByText(HASH)).toBeVisible();
  await expect(page.getByText("Signed. This note is locked.")).toBeVisible();
  await expect(page.getByRole("button", { name: /Sign note|Discard draft/ })).toHaveCount(0);
  await expect(line(page, PHYSICIAN)).toHaveCount(0);
  await line(page, FOCUS).click();
  await expect(card(page).getByRole("button", { name: /Wording|Edit line|Undo/ })).toHaveCount(0);
  await checkScreen(page, { night: true });
  await shot(page, "signed");

  // Back to the patient, inside the app: the signed note is in this shift's list.
  await page.getByRole("link", { name: "Back to Demo patient A" }).click();
  await expect(page.getByRole("heading", { name: "Demo patient A" })).toBeVisible();
  const shiftNotes = page.getByRole("region", { name: "Notes this shift" });
  await expect(shiftNotes.getByRole("link", { name: "Signed" })).toBeVisible();
  await checkScreen(page);
  await shot(page, "patient-signed");

  // Sign out and sign in as the US staff nurse: her list holds only US patients, none of the PH ones.
  await header.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("button", { name: EMILY })).toBeVisible();
  await page.getByRole("button", { name: EMILY }).click();
  await expect(page.getByRole("heading", { name: "Patients on this unit" })).toBeVisible();
  await expect(page.getByRole("link", { name: /Demo patient C/ })).toBeVisible();
  await expect(page.getByRole("link", { name: /Demo patient/ })).toHaveCount(1);
  await expect(page.getByRole("link", { name: /Demo patient [AB]/ })).toHaveCount(0);
  await expect(page.getByText("Demo patient A")).toHaveCount(0);
  await checkScreen(page);
});

test("PH flow by keyboard alone: every step with Tab, Enter, arrows and Escape", async ({
  page,
}) => {
  // Sign-in: Tab to the persona, Enter.
  await page.goto("/sign-in");
  const sarah = page.getByRole("button", { name: SARAH });
  await expect(sarah).toBeVisible();
  await checkScreen(page);
  await tabTo(page, sarah, 10);
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Patients on this ward" })).toBeVisible();

  // The list: Tab to the patient row, Enter.
  const row = page.getByRole("link", { name: /Demo patient A/ });
  await expect(row).toBeVisible();
  await checkScreen(page);
  await tabTo(page, row, 12);
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Demo patient A" })).toBeVisible();

  // The patient page: Tab to the note, type, Tab to Save note, Enter.
  const box = page.getByLabel("Your note");
  await tabTo(page, box, 12);
  await page.keyboard.type(ROUGH_NOTE);
  await checkScreen(page);
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Save note" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(NOTE_URL, { timeout: 8000 });
  await expect(page.getByRole("heading", { name: "Your note" })).toBeVisible();
  await checkScreen(page);

  // Three lines: Tab to a line, Enter, Tab to its action, Enter.
  await tabTo(page, line(page, FOCUS));
  await page.keyboard.press("Enter");
  await tabTo(page, card(page).getByRole("button", { name: "Wording is right" }));
  await page.keyboard.press("Enter");
  await expect(line(page, FOCUS)).toContainText("Checked by you");
  await expect(line(page, FOCUS)).toBeFocused();

  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  await expect(line(page, D2)).toBeFocused();
  await checkScreen(page);
  await tabTo(page, card(page).getByRole("button", { name: "Use 112 from your note" }));
  await page.keyboard.press("Enter");
  await expect(line(page, /^BP 90\/60 mmHg, HR 112 bpm/)).toContainText("Edited by you");

  await tabTo(page, line(page, PHYSICIAN));
  await page.keyboard.press("Enter");
  await tabTo(page, card(page).getByRole("button", { name: "Remove line" }));
  await page.keyboard.press("Enter");
  await expect(line(page, PHYSICIAN)).toContainText("Removed by you");

  // Sign note opens the dialog; Escape cancels it and the focus goes back.
  const sign = page.getByRole("button", { name: "Sign note" });
  await tabTo(page, sign);
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "Sign this FDAR note" });
  await expect(dialog).toBeVisible();
  // It opens on the safe choice: a held Enter on Sign note can't go on to sign.
  await expect(dialog.getByRole("button", { name: "Cancel" })).toBeFocused();
  await checkScreen(page);
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(sign).toBeFocused();

  await page.keyboard.press("Enter");
  await expect(dialog).toBeVisible();
  // The focus is trapped in the dialog: Tab goes round its two buttons and never leaves.
  for (let i = 0; i < 4; i++) {
    await page.keyboard.press("Tab");
    expect(await dialog.evaluate((el) => el.contains(document.activeElement))).toBe(true);
  }
  await tabTo(page, dialog.getByRole("button", { name: "Sign note" }));
  await page.keyboard.press("Enter");
  await expect(page.getByText(SIGNED_AT)).toBeVisible();
  await expect(page.getByText(HASH)).toBeVisible();
  await expect(page.getByText("Signed. This note is locked.")).toBeVisible();
  await checkScreen(page);
});

test("US path: DAR draft, shift 7a-7p, times in Pacific time", async ({ page }, testInfo) => {
  // One width is enough for the region words; the layout is proven by the PH flow at all three.
  test.skip(testInfo.project.name !== projectAt(375), "The US path runs at 375 px only.");

  // The demo data's instants, worded in the US facility's zone with its 24-hour clock (the demo
  // profile's `clock`). Worked out here, not copied off the screen: 15:00Z is 07:00 in Pacific
  // standard time, 03:00Z the next day is 19:00, and the typed note is stamped 10:15 at -08:00.
  const pacific = (iso: string) =>
    new Intl.DateTimeFormat("en-US", {
      timeZone: "America/Los_Angeles",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    }).format(new Date(iso));
  const shiftStart = pacific("2026-11-12T15:00:00Z");
  const shiftEnd = pacific("2026-11-13T03:00:00Z");
  const typedAt = pacific("2026-11-12T10:15:00-08:00");
  expect([shiftStart, shiftEnd, typedAt]).toEqual(["07:00", "19:00", "10:15"]);
  // Manila's reading of the same instants differs, so a wrong zone could not pass by luck.
  expect(
    new Intl.DateTimeFormat("en-US", {
      timeZone: "Asia/Manila",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    }).format(new Date("2026-11-12T10:15:00-08:00")),
  ).toBe("02:15");

  await signInAs(page, EMILY, "Patients on this unit");
  const header = page.getByRole("banner");
  await expect(header.getByText("Emily Carter, RN")).toBeVisible();
  await expect(header.getByText("Shift 7a-7p")).toBeVisible();
  await expectHeaderAtMostTwoRows(page);
  await expect(page.getByText(`${shiftStart} to ${shiftEnd} 12 Nov 2026`)).toBeVisible();
  await checkScreen(page);
  await shot(page, "us-list");

  await page.getByRole("link", { name: /Demo patient C/ }).click();
  await expect(page.getByRole("heading", { name: "Demo patient C" })).toBeVisible();
  const main = page.getByRole("main");
  // The US words: Room (not Bed), and the date after the day, in the facility's clock.
  await expect(main.getByText("Room", { exact: true })).toBeVisible();
  await expect(main.getByText("78 M, Med-Surg")).toBeVisible();
  await expect(
    main.getByText(`Shift 7a-7p · ${shiftStart} to ${shiftEnd} 12 Nov 2026`),
  ).toBeVisible();
  await page.getByLabel("Your note").fill("0830 pt A&Ox4, c/o R hip pain 6/10");
  await checkScreen(page);
  await page.getByRole("button", { name: "Save note" }).click();
  await expect(page).toHaveURL(NOTE_URL, { timeout: 8000 });
  await expect(page.getByRole("heading", { name: "Your note" })).toBeVisible();

  // The draft is labelled DAR (never FDAR), the shift is 7a-7p, and the typed time is Pacific.
  await expect(
    page.getByText(
      `78 M, Med-Surg. DAR note for the 7a-7p shift, ${shiftStart} to ${shiftEnd} 12 Nov 2026.`,
    ),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "DAR draft" })).toBeVisible();
  await expect(page.getByText("FDAR")).toHaveCount(0);
  await expect(page.getByText(`Typed at ${typedAt}. The AI never changes it.`)).toBeVisible();
  await expect(header.getByText("Shift 7a-7p")).toBeVisible();
  await checkScreen(page);
  await shot(page, "us-trace");
});

test.describe("admin path", () => {
  // Two widths: the small screen and the wide one. 768 is skipped (the layout between them is
  // covered by the PH flow and the settings spec).
  test("renames the 10-6 label, sees the US shifts, and the nurse sees the new label (keyboard only)", async ({
    page,
  }, testInfo) => {
    test.skip(testInfo.project.name === projectAt(768), "The admin path runs at 375 and 1280 px.");

    // Sign in as Admin: Settings only.
    await page.goto("/sign-in");
    const admin = page.getByRole("button", { name: ADMIN });
    await expect(admin).toBeVisible();
    await tabTo(page, admin);
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
    const header = page.getByRole("banner");
    await expect(header.getByText("Admin")).toBeVisible();
    await expect(header.getByRole("link", { name: "Patients" })).toHaveCount(0);
    await expect(header.getByRole("button", { name: "Change shift" })).toHaveCount(0);
    await expectHeaderAtMostTwoRows(page);
    const facilityName = page.getByRole("textbox", { name: "Facility name" });
    await expect(facilityName).toHaveValue("SYNTHETIC Demo Hospital (PH)");
    await expect(page.getByText("Changes apply to new notes.")).toBeVisible();
    await expect(page.getByRole("radio", { name: "Red" }).last()).toBeChecked();
    await checkScreen(page);

    // Rename the 10-6 label (the third shift) and save.
    const label = page.getByRole("group", { name: "Shift 3" }).getByLabel("Label");
    await expect(label).toHaveValue("10-6");
    await tabTo(page, label);
    await page.keyboard.press("ControlOrMeta+a");
    await page.keyboard.type("Night");
    await tabTo(page, page.getByRole("button", { name: "Save settings" }));
    await page.keyboard.press("Enter");
    await expect(page.getByRole("status")).toContainText("Saved.");
    await expect(label).toHaveValue("Night");
    await checkScreen(page);
    await shot(page, "settings");

    // Switch to the US facility (nothing unsaved, so no question): its 7a-7p and 7p-7a.
    const facility = page.getByRole("combobox", { name: "Facility" });
    await tabTo(page, facility);
    await page.keyboard.press("ArrowDown");
    await expect(facilityName).toHaveValue("SYNTHETIC Demo Hospital (US)");
    await expect(page.getByRole("group", { name: "Shift 1" }).getByLabel("Label")).toHaveValue(
      "7a-7p",
    );
    await expect(page.getByRole("group", { name: "Shift 2" }).getByLabel("Label")).toHaveValue(
      "7p-7a",
    );
    await expect(page.getByRole("group", { name: "Shift 3" })).toHaveCount(0);
    await checkScreen(page);

    // Sign out, sign in as the PH staff nurse: the header shows the new label.
    const signOut = header.getByRole("button", { name: "Sign out" });
    await tabTo(page, signOut);
    await page.keyboard.press("Enter");
    const sarah = page.getByRole("button", { name: SARAH });
    await expect(sarah).toBeVisible();
    await tabTo(page, sarah);
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { name: "Patients on this ward" })).toBeVisible();
    await expect(header.getByText("Shift Night")).toBeVisible();
    await expectHeaderAtMostTwoRows(page);
    await checkScreen(page);
  });
});
