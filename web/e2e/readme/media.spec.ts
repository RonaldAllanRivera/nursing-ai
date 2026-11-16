// Makes the README's pictures against the real stack in replay mode (`make readme-media`).
// Replay serves the recorded draft only for a note typed exactly as a demo case's, so the notes
// here come from the demo cases. Synthetic personas and patients only.
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readdirSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";
import {
  ADMIN,
  EMILY,
  card,
  demoNoteText,
  draftLines,
  openPatient,
  resolveEveryLine,
  saveNote,
  signInAs,
  signNote,
} from "../real/helpers.ts";

const MEDIA = fileURLToPath(new URL("../../../docs/media/", import.meta.url));
const AID = "Documentation aid — the nurse reviews and signs every note.";
const beat = (page: Page, ms = 1200) => page.waitForTimeout(ms);

async function expectAidLine(page: Page) {
  await expect(page.getByText(AID).first()).toBeVisible();
}

test.beforeAll(() => mkdirSync(MEDIA, { recursive: true }));

test("GIF: the Philippine flow, from a rough note to a locked note", async ({ browser }) => {
  const dir = mkdtempSync(join(tmpdir(), "readme-video-"));
  const size = { width: 1100, height: 760 };
  const context = await browser.newContext({
    viewport: size,
    timezoneId: "UTC",
    recordVideo: { dir, size },
  });
  const page = await context.newPage();
  await openPatient(page, "Demo patient A");
  await expectAidLine(page);
  const text = demoNoteText("demo-1");
  await page.getByLabel("Your note").pressSequentially(text, { delay: 8 });
  await beat(page, 800);
  await page.getByRole("button", { name: "Save note" }).click();
  await expect(draftLines(page).first()).toBeVisible({ timeout: 90_000 });
  await beat(page);
  // Tap a line with source words: they light up in the note.
  const count = await draftLines(page).count();
  for (let i = 0; i < count; i++) {
    await draftLines(page).nth(i).click();
    await expect(card(page)).toBeVisible();
    if ((await page.locator(".note-text mark.hl").count()) > 0) break;
  }
  await beat(page, 2200);
  await resolveEveryLine(page);
  await beat(page, 900);
  await signNote(page);
  await beat(page, 2200);
  await page.close();
  const video = readdirSync(dir).find((f) => f.endsWith(".webm"));
  if (!video) throw new Error("No video was recorded.");
  await context.close();
  const input = join(dir, video);
  const palette = join(dir, "palette.png");
  // Palette-based GIF: 800 px wide, 5 frames a second, at most 15 seconds.
  const filters = "fps=5,scale=800:-1:flags=lanczos";
  const speed = process.env["GIF_SPEED"] ?? "1";
  const pre = `setpts=PTS/${speed},${filters}`;
  execFileSync("ffmpeg", [
    "-v",
    "error",
    "-y",
    "-i",
    input,
    "-vf",
    `${pre},palettegen=max_colors=48:stats_mode=diff`,
    palette,
  ]);
  const out = join(MEDIA, "ph-flow.gif");
  execFileSync("ffmpeg", [
    "-v",
    "error",
    "-y",
    "-i",
    input,
    "-i",
    palette,
    "-t",
    "15",
    "-lavfi",
    `${pre}[x];[x][1:v]paletteuse=dither=none:diff_mode=rectangle`,
    out,
  ]);
  rmSync(dir, { recursive: true, force: true });
  expect(statSync(out).size).toBeLessThan(2_000_000);
});

test("Screenshots: the trace view, the signed note, the US DAR draft and Settings", async ({
  browser,
}) => {
  const shot = (page: Page, name: string, fullPage = false) =>
    page.screenshot({ path: join(MEDIA, name), scale: "css", fullPage });

  // The trace view on a tablet: a line selected, its source words lit in the note.
  const tablet = await browser.newContext({ viewport: { width: 768, height: 1500 } });
  const t = await tablet.newPage();
  await openPatient(t, "Demo patient A");
  await saveNote(t, demoNoteText("demo-1"));
  const count = await draftLines(t).count();
  for (let i = 0; i < count; i++) {
    await draftLines(t).nth(i).click();
    await expect(card(t)).toBeVisible();
    if ((await t.locator(".note-text mark.hl").count()) > 0) break;
  }
  await expect(t.locator(".note-text mark.hl").first()).toBeVisible();
  await expectAidLine(t);
  await beat(t, 600);
  await shot(t, "trace-view-tablet.png");

  // The signed view: every line checked, signed, locked, with its short hash.
  await resolveEveryLine(t);
  await signNote(t);
  await expectAidLine(t);
  await beat(t, 600);
  await shot(t, "signed-note.png");
  await tablet.close();

  // The US facility: a DAR draft, no Focus section, shift times in Pacific time.
  const us = await browser.newContext({ viewport: { width: 1100, height: 900 } });
  const u = await us.newPage();
  await signInAs(u, EMILY, "Patients on this unit");
  await u.getByRole("link", { name: /Demo patient C/ }).click();
  await expect(u.getByRole("heading", { name: "Demo patient C" })).toBeVisible();
  await saveNote(u, demoNoteText("demo-3"));
  await expect(u.getByRole("heading", { name: "DAR draft" })).toBeVisible();
  await draftLines(u).first().click();
  await expectAidLine(u);
  await beat(u, 600);
  await shot(u, "us-dar-draft.png");
  await us.close();

  // The admin's Settings: the facility's note format, zone, shifts and wording.
  const admin = await browser.newContext({ viewport: { width: 1100, height: 900 } });
  const a = await admin.newPage();
  await signInAs(a, ADMIN, "Settings");
  await expect(a.getByRole("textbox", { name: "Facility name" })).toBeVisible();
  await expectAidLine(a);
  await beat(a, 600);
  await shot(a, "admin-settings.png", true);
  await admin.close();
});
