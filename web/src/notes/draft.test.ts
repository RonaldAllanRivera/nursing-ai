import { describe, expect, it } from "vitest";
import type { components } from "../api/schema";
import { failureMessage, noteStatus, pollDelay } from "./draft";

type ShiftNote = components["schemas"]["ShiftNoteOut"];

describe("pollDelay", () => {
  it("pollDelay backs off from 1 s to 5 s", () => {
    expect([0, 1, 2, 3, 4, 5, 6, 20].map(pollDelay)).toEqual([
      1000, 1000, 2000, 3000, 5000, 5000, 5000, 5000,
    ]);
  });
});

describe("failureMessage", () => {
  it.each([
    ["ai_budget_reached", "Monthly AI budget reached. Your note is saved."],
    ["model_refused", "The AI declined to draft this note. Your note is saved."],
    [
      "invalid_output",
      "The AI's draft failed the app's checks, so it wasn't kept. Your note is saved.",
    ],
    ["provider_error", "The AI service didn't answer. Your note is saved."],
    ["replay_missing", "No recorded draft matches this note. Your note is saved."],
  ] as const)("says it for %s", (code, message) => {
    expect(failureMessage(code)).toBe(message);
  });

  it("falls back to a plain line that still says the note is saved", () => {
    expect(failureMessage("something_new" as never)).toBe(
      "The draft could not be made. Your note is saved.",
    );
    expect(failureMessage(null)).toBe("The draft could not be made. Your note is saved.");
  });
});

describe("noteStatus", () => {
  const base: ShiftNote = {
    rough_note_id: "r",
    written_at: "2026-11-11T14:30:00Z",
    note_status: null,
    job: { id: "j", rough_note_id: "r", status: "queued", failure: null, note_id: null },
  };

  it("says Drafting while the job runs", () => {
    expect(noteStatus(base)).toEqual({ kind: "drafting", label: "Drafting", noteId: null });
    expect(noteStatus({ ...base, job: { ...base.job, status: "running" } }).kind).toBe("drafting");
  });

  it("says Draft ready, with the note to open", () => {
    const ready = {
      ...base,
      note_status: "draft" as const,
      job: { ...base.job, status: "succeeded" as const, note_id: "n-1" },
    };
    expect(noteStatus(ready)).toEqual({ kind: "ready", label: "Draft ready", noteId: "n-1" });
  });

  it("says Signed and Discarded (and still links a signed note)", () => {
    const done = { ...base, job: { ...base.job, status: "succeeded" as const, note_id: "n-1" } };
    expect(noteStatus({ ...done, note_status: "signed" })).toEqual({
      kind: "signed",
      label: "Signed",
      noteId: "n-1",
    });
    expect(noteStatus({ ...done, note_status: "discarded" })).toEqual({
      kind: "discarded",
      label: "Discarded",
      noteId: null,
    });
  });

  it("gives the failure line for a failed job", () => {
    const failed = {
      ...base,
      job: { ...base.job, status: "failed" as const, failure: "provider_error" as const },
    };
    expect(noteStatus(failed)).toEqual({
      kind: "failed",
      label: "The AI service didn't answer. Your note is saved.",
      noteId: null,
    });
  });
});
