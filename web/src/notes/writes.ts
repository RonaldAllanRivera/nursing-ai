import { useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { ApiError, unwrap } from "../api/errors";
import type { components } from "../api/schema";
import { usePinRequest } from "../session/usePinRequest";
import { noteQuery } from "./note";

type Schemas = components["schemas"];
export type LineBody =
  Schemas["ConfirmLine"] | Schemas["EditLine"] | Schemas["RemoveLine"] | Schemas["RestoreLine"];

/** The note's address in the cache: a write's answer goes straight back into it. */
function entryKey(noteId: string) {
  return noteQuery(noteId).queryKey;
}

/** Every write to one note shares this scope, so TanStack runs them one after the other. */
function noteScope(noteId: string) {
  return `note:${noteId}`;
}

/** The tag of the version this screen shows: what a change must be made against. */
function currentEtag(queryClient: QueryClient, noteId: string): string | null {
  return queryClient.getQueryData(entryKey(noteId))?.etag ?? null;
}

function keepAnswer(
  queryClient: QueryClient,
  noteId: string,
  note: Schemas["NoteOut"],
  etag: string | null,
) {
  queryClient.setQueryData(entryKey(noteId), { note, etag });
}

/** Confirm, edit, remove or put back one line. The 200 is the whole new note, with its new ETag. */
export function useActOnLine(noteId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    // One write to a note at a time: the next one waits, and then sends the version the last returned.
    scope: { id: noteScope(noteId) },
    mutationFn: async ({ lineId, body }: { lineId: string; body: LineBody }) => {
      const answer = await api.PATCH("/api/v1/notes/{note_id}/lines/{line_id}", {
        params: {
          path: { note_id: noteId, line_id: lineId },
          header: { "If-Match": currentEtag(queryClient, noteId) },
        },
        body,
      });
      return { note: unwrap(answer), etag: answer.response.headers.get("ETag") };
    },
    // A refetch already under way would answer with the version from before this write.
    onMutate: () => queryClient.cancelQueries({ queryKey: entryKey(noteId) }),
    onSuccess: ({ note, etag }) => {
      keepAnswer(queryClient, noteId, note, etag);
    },
  });
}

/** A sign or a discard finished: its answer replaces the note, and this shift's list on the patient page is out of date. */
function keepFinished(
  queryClient: QueryClient,
  noteId: string,
  { note, etag }: { note: Schemas["NoteOut"]; etag: string | null },
) {
  keepAnswer(queryClient, noteId, note, etag);
  void queryClient.invalidateQueries({ queryKey: ["patient"] });
}

/** Discard the draft. It joins the note's one-at-a-time line of writes. */
export function useDiscardNote(noteId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    scope: { id: noteScope(noteId) },
    mutationFn: async () => {
      const answer = await api.POST("/api/v1/notes/{note_id}/discard", {
        params: {
          path: { note_id: noteId },
          header: { "If-Match": currentEtag(queryClient, noteId) },
        },
      });
      return { note: unwrap(answer), etag: answer.response.headers.get("ETag") };
    },
    onMutate: () => queryClient.cancelQueries({ queryKey: entryKey(noteId) }),
    onSuccess: (answer) => {
      keepFinished(queryClient, noteId, answer);
    },
  });
}

/**
 * Sign the note with the PIN that was typed. It goes through `usePinRequest`, so the PIN never
 * stays in TanStack's mutation cache, and it keeps what every write to a note does: it shares the
 * note's scope (so it waits for the writes before it), and it reads the version tag only when its
 * turn comes, so it is made against what the last write returned.
 */
export function useSignNote(
  noteId: string,
  handlers: { onSuccess: () => void; onError: (error: unknown, previous: unknown) => void },
) {
  const queryClient = useQueryClient();
  return usePinRequest(
    async (pin: string) => {
      const answer = await api.POST("/api/v1/notes/{note_id}/sign", {
        params: {
          path: { note_id: noteId },
          header: { "If-Match": currentEtag(queryClient, noteId) },
        },
        body: { pin },
      });
      return { note: unwrap(answer), etag: answer.response.headers.get("ETag") };
    },
    {
      onSuccess: (answer) => {
        keepFinished(queryClient, noteId, answer);
        handlers.onSuccess();
      },
      onError: handlers.onError,
    },
    {
      scope: noteScope(noteId),
      onMutate: () => queryClient.cancelQueries({ queryKey: entryKey(noteId) }),
    },
  );
}

/** What went wrong with a write, in the terms a screen acts on. */
export type WriteFailure =
  | { kind: "stale" }
  | { kind: "locked" }
  | { kind: "incomplete"; lineIds: string[] }
  | { kind: "other" };

export function failureOf(error: unknown): WriteFailure {
  if (error instanceof ApiError) {
    if (error.status === 412) return { kind: "stale" };
    if (error.status === 409 && error.problem?.code === "note_locked") return { kind: "locked" };
    if (error.status === 409 && error.problem?.code === "review_incomplete") {
      return { kind: "incomplete", lineIds: error.problem.line_ids ?? [] };
    }
  }
  return { kind: "other" };
}

/**
 * Fetch the latest note again (a 412 or a lock means this screen is behind). `done` runs only when
 * the fresh note arrived; if it could not be fetched the failure stays, so the nurse can try again.
 */
export function useReloadNote(noteId: string) {
  const queryClient = useQueryClient();
  return async (done: () => void) => {
    await queryClient.refetchQueries({ queryKey: entryKey(noteId), exact: true });
    if (queryClient.getQueryState(entryKey(noteId))?.status !== "error") done();
  };
}
