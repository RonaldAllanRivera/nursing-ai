import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";
import { readSessionFrom } from "../api/client";
import { ApiError } from "../api/errors";
import { queryRetryDelay, retryQuery } from "../api/retry";
import { isWaking, wakeRetryDelay } from "../api/waking";
import { HELD_NOTE_ROOT } from "../notes/heldNote";
import { gateFromProblem } from "../session/gate";
import { sessionKey, type Session } from "../session/session";

/** A write is retried only when the database was waking: that answer means nothing was written. */
export function retryMutation(failureCount: number, error: Error): boolean {
  return isWaking(error) && wakeRetryDelay(failureCount) !== null;
}

/** Used by a write only when it opts into `retry`: 0.5 s, then 1 s; a waking database 5 s. */
export function mutationRetryDelay(failureCount: number, error: Error): number {
  if (isWaking(error)) return wakeRetryDelay(failureCount) ?? 5000;
  return failureCount === 0 ? 500 : 1000;
}

/**
 * One per app. Tests build their own with `retry: false`. A 401 from any query or mutation means the session
 * is gone: the session query becomes "signed out", and the shell sends you to /sign-in. A 423 moves the cached
 * session to the gate it names, and nothing else: the page under it keeps what she typed. A 403 `csrf_failed`
 * fetches the session again, which brings a fresh token for the next write.
 */
export function createQueryClient() {
  const followServer = (error: Error) => {
    if (!(error instanceof ApiError)) return;
    if (error.status === 401) {
      // Whatever she had typed and not sent goes with the session.
      queryClient.removeQueries({ queryKey: [HELD_NOTE_ROOT] });
      queryClient.setQueryData(sessionKey, null);
      return;
    }
    const gate = gateFromProblem(error.problem);
    if (gate !== null) {
      queryClient.setQueryData<Session | null>(sessionKey, (session) =>
        session ? { ...session, gate } : session,
      );
    } else if (error.status === 403 && error.problem?.code === "csrf_failed") {
      void queryClient.invalidateQueries({ queryKey: sessionKey });
    }
  };
  const queryClient: QueryClient = new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 5_000,
        refetchOnWindowFocus: false,
        retry: retryQuery,
        retryDelay: queryRetryDelay,
      },
      mutations: { retry: retryMutation, retryDelay: mutationRetryDelay },
    },
    queryCache: new QueryCache({ onError: followServer }),
    mutationCache: new MutationCache({ onError: followServer }),
  });
  // The unsent rough note outlives the page's unmounting for as long as a gate screen takes.
  queryClient.setQueryDefaults([HELD_NOTE_ROOT], { gcTime: Infinity });
  readSessionFrom(() => queryClient.getQueryData<Session | null>(sessionKey));
  return queryClient;
}
