import {
  queryOptions,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";
import { api } from "../api/client";
import { ensureOk, unwrap } from "../api/errors";
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

export function useSession() {
  return useQuery(sessionQuery);
}

export const personasQuery = queryOptions({
  queryKey: ["personas"],
  queryFn: async ({ signal }) => unwrap(await api.GET("/api/v1/personas", { signal })),
});

/** Nothing the last person saw may show for the next one: drop everything but who is signed in (and the sign-in list). */
export function clearPersonData(queryClient: QueryClient) {
  const keep = new Set<unknown>([sessionKey[0], personasQuery.queryKey[0]]);
  queryClient.removeQueries({ predicate: (query) => !keep.has(query.queryKey[0]) });
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
    },
  });
}
