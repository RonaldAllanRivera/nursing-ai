import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";
import { readSessionFrom } from "../api/client";
import { ApiError } from "../api/errors";
import { isWaking, wakeRetryDelay } from "../api/waking";
import { gateFromProblem } from "../session/gate";
import { sessionKey, type Session } from "../session/session";

/** TanStack's default (3 retries, so 4 tries), except a 4xx answer: the server meant it, so ask no more. A waking database is waited out instead. */
export function retryQuery(failureCount: number, error: Error): boolean {
  if (isWaking(error)) return wakeRetryDelay(failureCount) !== null;
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
  return failureCount < 3;
}

/** A write is retried only when the database was waking: that answer means nothing was written. */
export function retryMutation(failureCount: number, error: Error): boolean {
  return isWaking(error) && wakeRetryDelay(failureCount) !== null;
}

/** A waking database is asked again every 5 s; anything else backs off like TanStack's default. */
export function queryRetryDelay(failureCount: number, error: Error): number {
  return wakeRetryDelay(failureCount) !== null && isWaking(error)
    ? 5000
    : Math.min(1000 * 2 ** failureCount, 30000);
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
  readSessionFrom(() => queryClient.getQueryData<Session | null>(sessionKey));
  return queryClient;
}
