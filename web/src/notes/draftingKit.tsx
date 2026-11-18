import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { components } from "../api/schema";
import type { MockOptions } from "../mocks/options";
import { renderApp } from "../test/render";
import { chooseAndUnlock } from "../test/signIn";

export type Schemas = components["schemas"];

export const PATIENT_A = "00000000-0000-4000-8000-000000000011";
export const AGAIN_URL = "*/api/v1/rough-notes/:id/draft-jobs";
export const SARAH = "Staff nurse · Sarah Navarro, RN";
export const AGAIN = "Try drafting again";
export const HINT = "To save a new note, change the text.";
export const SLOW = { timeout: 5000 };

/** Signs in as Sarah and opens demo patient A, with the mock (`options`) and handlers that win over it. */
export async function openPatientA(
  options: MockOptions = {},
  overrides: Parameters<typeof renderApp>[2] = [],
) {
  const app = await renderApp("/sign-in", options, overrides);
  await chooseAndUnlock(SARAH);
  await userEvent.click(await screen.findByRole("link", { name: /Demo patient A/ }));
  await screen.findByLabelText("Your note");
  return app;
}

/** The write form's queries (the shift list has its own Try drafting again too). */
export const form = () => {
  const found = screen.getByLabelText("Your note").closest("form");
  if (!found) throw new Error("no form");
  return within(found);
};

/** Types a note and saves it with the mock set to fail that draft on purpose. */
export async function saveAFailedDraft(failure: NonNullable<MockOptions["failDraft"]>) {
  const app = await openPatientA({ failDraft: failure });
  await userEvent.click(screen.getByLabelText("Your note"));
  await userEvent.paste("pt c/o hilo");
  await userEvent.click(screen.getByRole("button", { name: "Save note" }));
  return app;
}

/** A draft job as the API answers it, a retryable failure unless changed. */
export const job = (extra: Partial<Schemas["DraftJobOut"]> = {}): Schemas["DraftJobOut"] => ({
  id: "00000000-0000-4000-8000-000000000f01",
  rough_note_id: "00000000-0000-4000-8000-000000000e01",
  status: "failed",
  failure: "provider_error",
  note_id: null,
  retryable: true,
  ...extra,
});

/** One row of this shift's list. */
export const rowFor = (
  current: Schemas["DraftJobOut"],
  at = "2026-11-11T14:30:00Z",
): Schemas["ShiftNoteOut"] => ({
  rough_note_id: current.rough_note_id,
  written_at: at,
  note_status: current.status === "succeeded" ? "draft" : null,
  job: current,
});

export const problem = (status: number, code: string) =>
  ({ type: "about:blank", title: code, status, code }) as const;
