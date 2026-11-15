import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";
import { ApiError } from "../api/errors";
import { sessionKey } from "../session/session";

/**
 * One per app. Tests build their own with `retry: false`. A 401 from any query or mutation means the session
 * is gone: the session query becomes "signed out", and the shell sends you to /sign-in.
 */
export function createQueryClient() {
  const endSessionOn401 = (error: Error) => {
    if (error instanceof ApiError && error.status === 401) {
      queryClient.setQueryData(sessionKey, null);
    }
  };
  const queryClient: QueryClient = new QueryClient({
    defaultOptions: { queries: { staleTime: 5_000, refetchOnWindowFocus: false } },
    queryCache: new QueryCache({ onError: endSessionOn401 }),
    mutationCache: new MutationCache({ onError: endSessionOn401 }),
  });
  return queryClient;
}
