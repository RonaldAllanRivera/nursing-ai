import {
  queryOptions,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";
import { api } from "../api/client";
import { ApiError, ensureOk, unwrap } from "../api/errors";
import { demoEndedReason } from "./pin";
import { usePinRequest } from "./usePinRequest";
import { retryOptions } from "../api/retry";
import type { components } from "../api/schema";

export type Session = components["schemas"]["SessionOut"];

export const sessionKey = ["session"] as const;

/** The signed-in person, or `null` when there is no session (a 401 is an answer, not a failure). */
export const sessionQuery = queryOptions({
  queryKey: sessionKey,
  queryFn: async ({ signal }): Promise<Session | null> => {
    const answer = await api.GET("/api/v1/session", { signal });
    if (answer.response.status === 401) return null;
    return unwrap(answer);
  },
});

/**
 * Stores the session a write answered (sign-in, unlock, set PIN, shift, sign-out). Any session
 * request still out was asked about the person before this answer, so it is cancelled first: a
 * slower answer must not put the old person back. (Whether the stored session is someone else's
 * is decided in one place, `createQueryClient`, whoever wrote it.)
 */
export async function storeSession(queryClient: QueryClient, session: Session | null) {
  await queryClient.cancelQueries({ queryKey: sessionKey });
  queryClient.setQueryData(sessionKey, session);
}

export function useSession() {
  return useQuery(sessionQuery);
}

export const personasQuery = queryOptions({
  queryKey: ["personas"],
  queryFn: async ({ signal }) => unwrap(await api.GET("/api/v1/personas", { signal })),
});

/**
 * What the sign-in page offers. It never touches the database, so it is safe to ask on every
 * screen (the demo banner reads it too). One failure must not cost the whole visit its banner or
 * its Google link, so it follows the app's retry rules; only a 501 (no auth on this server yet)
 * stops at once, and the screen falls back to the persona list.
 */
export const signInOptionsQuery = queryOptions({
  queryKey: ["sign-in-options"],
  queryFn: async ({ signal }) => unwrap(await api.GET("/api/v1/sign-in-options", { signal })),
  retry: retryOptions,
  staleTime: 5 * 60_000,
});

/**
 * Nothing the last person saw may show for the next one: drop everything but who is signed in (and
 * the sign-in list and options, which are not about a person), and every finished, pending or
 * failed write (it holds her typed text).
 */
export function clearPersonData(queryClient: QueryClient) {
  const keep = new Set<unknown>([
    sessionKey[0],
    personasQuery.queryKey[0],
    signInOptionsQuery.queryKey[0],
    // Why a session ended on its own; shown on the sign-in screen, gone when a person signs in.
    signInNoticeKey[0],
  ]);
  queryClient.removeQueries({ predicate: (query) => !keep.has(query.queryKey[0]) });
  queryClient.getMutationCache().clear();
}

export function useSignIn() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (personaId: string) =>
      unwrap(await api.POST("/api/v1/session", { body: { persona_id: personaId } })),
    onSuccess: async (session) => {
      clearPersonData(queryClient);
      await storeSession(queryClient, session);
    },
  });
}

/**
 * Why the sign-in screen is showing after a session ended on its own: a demo session's `"fifth"`
 * (a fifth wrong PIN) or `"expired"`, `"pin_wait"` for a first PIN chosen after the session ran
 * out, or `{ hours }` for a session that reached its hard limit. It goes when a person signs in.
 */
export type SignInNotice = "fifth" | "expired" | "pin_wait" | { hours: number } | false;
export const signInNoticeKey = ["sign-in-notice"] as const;

/** A 409 at a PIN screen means the session moved on elsewhere (another window opened it or set the PIN): look again, and the right screen shows. */
function lookAgainOnConflict(queryClient: QueryClient, error: unknown) {
  if (error instanceof ApiError && error.status === 409) {
    void queryClient.invalidateQueries({ queryKey: sessionKey });
  }
}

/** Sets the first PIN of a Google user's first sign-in. Success answers the open session. */
export function useSetPin() {
  const queryClient = useQueryClient();
  return usePinRequest(
    async (pin: string) => unwrap(await api.POST("/api/v1/session/pin", { body: { pin } })),
    {
      // Not clearPersonData: the page under the gate, and the note she was typing, come back.
      onSuccess: (session) => storeSession(queryClient, session),
      onError: (error) => {
        lookAgainOnConflict(queryClient, error);
        // A 401 here is final (the PIN is never sent again): the wait to choose one outlived the session.
        if (error instanceof ApiError && error.status === 401) {
          queryClient.setQueryData<SignInNotice>(signInNoticeKey, "pin_wait");
        }
      },
    },
  );
}

/**
 * After a PIN request failed for a demo person: a 401 means the session already ended (the fifth
 * wrong PIN, or it ran out), and the sign-in screen says which. The hours it lasted, if an
 * earlier 401 already said so, are the better answer.
 */
export function explainDemoEnd(queryClient: QueryClient, error: unknown, previous: unknown) {
  const reason = demoEndedReason(error, previous);
  if (reason && !queryClient.getQueryData(signInNoticeKey)) {
    queryClient.setQueryData(signInNoticeKey, reason);
  }
}

/**
 * Proves who is at the keyboard (after sign-in, or after an idle lock). A demo person's 401 has
 * already signed the app out; this says why on the sign-in screen.
 */
export function useUnlock(persona: boolean) {
  const queryClient = useQueryClient();
  return usePinRequest(
    async (pin: string) => unwrap(await api.POST("/api/v1/session/unlock", { body: { pin } })),
    {
      onSuccess: (session) => storeSession(queryClient, session),
      onError: (error, previous) => {
        lookAgainOnConflict(queryClient, error);
        if (persona) explainDemoEnd(queryClient, error, previous);
      },
    },
  );
}

export function useSignOut() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      ensureOk(await api.DELETE("/api/v1/session"));
    },
    onSuccess: async () => {
      clearPersonData(queryClient);
      await storeSession(queryClient, null);
    },
  });
}

export function useChangeShift() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (startsAt: string) =>
      unwrap(await api.PUT("/api/v1/session/shift", { body: { starts_at: startsAt } })),
    onSuccess: async (session) => {
      await storeSession(queryClient, session);
      // A patient's page shows the session's shift and its notes.
      void queryClient.invalidateQueries({ queryKey: ["patient"] });
    },
  });
}
