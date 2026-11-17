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

/**
 * The signed-in person, or `null` when there is no session (a 401 is an answer, not a failure).
 * Everything cached is about one person: when an answer names someone else (another tab signed
 * in as another nurse and the shared cookie changed) or nobody, the last person's data is
 * dropped here, before the new answer is stored and anything renders with it.
 */
export const sessionQuery = queryOptions({
  queryKey: sessionKey,
  queryFn: async ({ signal, client }): Promise<Session | null> => {
    const answer = await api.GET("/api/v1/session", { signal });
    const next = answer.response.status === 401 ? null : unwrap(answer);
    const previous = client.getQueryData<Session | null>(sessionKey);
    if (previous && previous.user_id !== next?.user_id) clearPersonData(client);
    return next;
  },
});

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
  ]);
  queryClient.removeQueries({ predicate: (query) => !keep.has(query.queryKey[0]) });
  queryClient.getMutationCache().clear();
}

export function useSignIn() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (personaId: string) =>
      unwrap(await api.POST("/api/v1/session", { body: { persona_id: personaId } })),
    onSuccess: (session) => {
      clearPersonData(queryClient);
      queryClient.setQueryData(sessionKey, session);
    },
  });
}

/** Why the sign-in screen is showing after a demo session ended on its own: `"fifth"` (a fifth wrong PIN) or `"expired"`. It goes when a person is chosen. */
export const demoEndedKey = ["sign-in-notice"] as const;

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
      onSuccess: (session) => {
        queryClient.setQueryData(sessionKey, session);
      },
      onError: (error) => {
        lookAgainOnConflict(queryClient, error);
      },
    },
  );
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
      onSuccess: (session) => {
        queryClient.setQueryData(sessionKey, session);
      },
      onError: (error, previous) => {
        lookAgainOnConflict(queryClient, error);
        const reason = persona ? demoEndedReason(error, previous) : null;
        if (reason) queryClient.setQueryData(demoEndedKey, reason);
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
    onSuccess: () => {
      clearPersonData(queryClient);
      queryClient.setQueryData(sessionKey, null);
    },
  });
}

export function useChangeShift() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (startsAt: string) =>
      unwrap(await api.PUT("/api/v1/session/shift", { body: { starts_at: startsAt } })),
    onSuccess: (session) => {
      queryClient.setQueryData(sessionKey, session);
      // A patient's page shows the session's shift and its notes.
      void queryClient.invalidateQueries({ queryKey: ["patient"] });
    },
  });
}
