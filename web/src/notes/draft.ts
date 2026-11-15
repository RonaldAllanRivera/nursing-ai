import type { components } from "../api/schema";

type JobFailure = components["schemas"]["JobFailure"];
type ShiftNote = components["schemas"]["ShiftNoteOut"];

const DELAYS = [1000, 1000, 2000, 3000, 5000];

/** How long to wait before the next look at a draft job: 1 s at first, backing off to 5 s. */
export function pollDelay(attempt: number): number {
  return DELAYS[Math.min(Math.max(attempt, 0), DELAYS.length - 1)] ?? 5000;
}

const MESSAGES: Record<JobFailure, string> = {
  ai_budget_reached: "Monthly AI budget reached. Your note is saved.",
  model_refused: "The AI declined to draft this note. Your note is saved.",
  invalid_output: "The AI's draft failed the app's checks, so it wasn't kept. Your note is saved.",
  provider_error: "The AI service didn't answer. Your note is saved.",
  replay_missing: "No recorded draft matches this note. Your note is saved.",
};

/** One plain line for a failed draft. An unknown code still says the note is saved. */
export function failureMessage(failure: JobFailure | null | undefined): string {
  return (
    (failure ? MESSAGES[failure] : undefined) ?? "The draft could not be made. Your note is saved."
  );
}

export type NoteStatusKind = "drafting" | "ready" | "signed" | "discarded" | "failed";

/** What a note in this shift's list says, and the note to open (if there is one). */
export function noteStatus(item: ShiftNote): {
  kind: NoteStatusKind;
  label: string;
  noteId: string | null;
} {
  const { job, note_status } = item;
  if (job.status === "failed") {
    return { kind: "failed", label: failureMessage(job.failure), noteId: null };
  }
  if (job.status !== "succeeded") return { kind: "drafting", label: "Drafting", noteId: null };
  if (note_status === "discarded") return { kind: "discarded", label: "Discarded", noteId: null };
  if (note_status === "signed") return { kind: "signed", label: "Signed", noteId: job.note_id };
  return { kind: "ready", label: "Draft ready", noteId: job.note_id };
}
