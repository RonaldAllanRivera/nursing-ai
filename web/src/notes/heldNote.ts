import type { QueryClient } from "@tanstack/react-query";
import { sessionKey, type Session } from "../session/session";

/** The root of every held note's key, so the client can give them all a lifetime that never ends. */
export const HELD_NOTE_ROOT = "held-note";

/** A held note belongs to whoever was signed in when she typed it; nobody else is ever handed it. */
interface Held {
  text: string;
  owner: string | null;
}

const ownerOf = (queryClient: QueryClient) =>
  queryClient.getQueryData<Session | null>(sessionKey)?.user_id ?? null;

const keyFor = (patientId: string) => [HELD_NOTE_ROOT, patientId] as const;

/**
 * The rough note a nurse is typing is kept in memory (the query cache, never the browser's storage)
 * so a gate screen that replaces the page for a while doesn't cost her the text. Unsent text only:
 * the cache's `clearPersonData` and a 401 drop it with the rest of the person's data, and it is
 * only given back to the person who typed it.
 */
export function readHeldNote(queryClient: QueryClient, patientId: string): string {
  const held = queryClient.getQueryData<Held>(keyFor(patientId));
  return held && held.owner === ownerOf(queryClient) ? held.text : "";
}

/** Keeps `text` for this patient; an empty note keeps nothing. */
export function holdNote(queryClient: QueryClient, patientId: string, text: string) {
  if (text === "") queryClient.removeQueries({ queryKey: keyFor(patientId) });
  else queryClient.setQueryData<Held>(keyFor(patientId), { text, owner: ownerOf(queryClient) });
}
