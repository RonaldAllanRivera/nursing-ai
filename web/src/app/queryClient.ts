import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";
import { readSessionFrom } from "../api/client";
import { ApiError } from "../api/errors";
import { resetRequestClock } from "../api/requestClock";
import { queryRetryDelay, retryQuery } from "../api/retry";
import { isWaking, wakeRetryDelay } from "../api/waking";
import { HELD_NOTE_ROOT } from "../notes/heldNote";
import { gateFromProblem, patchGate } from "../session/gate";
import { isPastExpiry, sessionHours } from "../session/expiry";
import {
  clearPersonData,
  signInNoticeKey,
  sessionKey,
  type Session,
  type SignInNotice,
} from "../session/session";

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
      queryClient.setQueryData(sessionKey, null);
      return;
    }
    const gate = gateFromProblem(error.problem);
    if (gate !== null) {
      patchGate(queryClient, gate);
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
  // The one place that decides a different person is signed in: whoever wrote the session (a
  // refetch, sign-in, unlock, set PIN, shift change, a 401), when its user differs from the last
  // one (another person, or nobody), the last person's data is dropped at once, synchronously,
  // before React is told, so nothing renders as the new person over the old person's cache.
  let lastUser: string | null | undefined;
  let lastSession: Session | undefined;
  queryClient.getQueryCache().subscribe((event) => {
    if (event.type !== "updated") return;
    const key = event.query.queryKey as readonly unknown[];
    if (key[0] !== sessionKey[0]) return;
    const data = event.query.state.data as Session | null | undefined;
    if (data === undefined) return;
    const user = data?.user_id ?? null;
    const changed = lastUser !== undefined && user !== lastUser;
    const before = lastSession;
    lastUser = user;
    if (data) lastSession = data;
    if (!changed) return;
    // The session was last seen past its hard limit and now there is nobody: it ran out. Read the
    // facility's hours before the data (the facility with it) goes.
    const ranOut =
      user === null && before && isPastExpiry(before.expires_at, Date.now())
        ? { hours: sessionHours(queryClient, before) }
        : null;
    clearPersonData(queryClient);
    if (ranOut) queryClient.setQueryData<SignInNotice>(signInNoticeKey, ranOut);
    // Someone signing in answers why the last session ended.
    if (user !== null && queryClient.getQueryData(signInNoticeKey)) {
      queryClient.setQueryData(signInNoticeKey, false);
    }
  });
  readSessionFrom(() => queryClient.getQueryData<Session | null>(sessionKey));
  // A new app has sent nothing yet.
  resetRequestClock();
  return queryClient;
}
