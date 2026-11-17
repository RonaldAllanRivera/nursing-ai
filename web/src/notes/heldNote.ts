import type { QueryClient } from "@tanstack/react-query";

/** The root of every held note's key, so the client can give them all a lifetime that never ends. */
export const HELD_NOTE_ROOT = "held-note";

const keyFor = (patientId: string) => [HELD_NOTE_ROOT, patientId] as const;

/**
 * The rough note a nurse is typing is kept in memory (the query cache, never the browser's storage)
 * so a gate screen that replaces the page for a while doesn't cost her the text. Unsent text only:
 * the cache's `clearPersonData` and a 401 drop it with the rest of the person's data.
 */
export function readHeldNote(queryClient: QueryClient, patientId: string): string {
  return queryClient.getQueryData<string>(keyFor(patientId)) ?? "";
}

/** Keeps `text` for this patient; an empty note keeps nothing. */
export function holdNote(queryClient: QueryClient, patientId: string, text: string) {
  if (text === "") queryClient.removeQueries({ queryKey: keyFor(patientId) });
  else queryClient.setQueryData(keyFor(patientId), text);
}
