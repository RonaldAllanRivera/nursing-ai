import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef } from "react";
import { api } from "../api/client";
import { ApiError, unwrap } from "../api/errors";
import { patientQuery } from "../patients/patients";

export const DAILY_DRAFT_LIMIT = "You've reached today's draft limit. Try again tomorrow.";
export const DRAFT_AGAIN_FAILED = "Couldn't start the draft. Check your connection and try again.";

/** The server says this rough note already has its draft (a 409 `already_drafted`). */
export function isAlreadyDrafted(error: unknown): boolean {
  return (
    error instanceof ApiError && error.status === 409 && error.problem?.code === "already_drafted"
  );
}

/**
 * What a refused "Try drafting again" means for the screen: `stale` (someone already drafted it, or
 * it can't be retried: look at the list again, no error), or words to show.
 */
export function draftAgainOutcome(
  error: unknown,
): { kind: "stale" } | { kind: "words"; words: string } {
  if (error instanceof ApiError) {
    const code = error.problem?.code;
    if (error.status === 409 && (code === "already_drafted" || code === "not_retryable")) {
      return { kind: "stale" };
    }
    if (error.status === 429 && code === "daily_draft_limit") {
      return { kind: "words", words: DAILY_DRAFT_LIMIT };
    }
  }
  return { kind: "words", words: DRAFT_AGAIN_FAILED };
}

/**
 * Asks for a new draft of a rough note after a failure worth another try. The answer is the new
 * job (or the one already running: a double tap is harmless), which is then followed like a first
 * draft. A refusal because someone else already acted refreshes what the screen shows.
 */
export function useDraftAgain(patientId: string) {
  const queryClient = useQueryClient();
  // Set the moment a request leaves, before React has drawn the busy button: a fast second tap is ignored.
  const out = useRef(false);
  const mutation = useMutation({
    mutationFn: async (roughNoteId: string) =>
      unwrap(
        await api.POST("/api/v1/rough-notes/{rough_note_id}/draft-jobs", {
          params: { path: { rough_note_id: roughNoteId } },
        }),
      ),
    onSuccess: () => {
      // The shift list shows this rough note's newest job: now the new one.
      void queryClient.invalidateQueries({ queryKey: patientQuery(patientId).queryKey });
    },
    onError: (error) => {
      if (draftAgainOutcome(error).kind !== "stale") return;
      void queryClient.invalidateQueries({ queryKey: patientQuery(patientId).queryKey });
    },
    onSettled: () => {
      out.current = false;
    },
  });
  /** Sends the request unless one is already out. */
  const ask: typeof mutation.mutate = (roughNoteId, options) => {
    if (out.current) return;
    out.current = true;
    mutation.mutate(roughNoteId, options);
  };
  return { ...mutation, ask };
}
