import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";
import { ApiError } from "../api/errors";
import { sessionKey } from "../session/session";

/** TanStack's default (3 tries), except a 4xx answer: the server meant it, so ask no more. */
export function retryQuery(failureCount: number, error: Error): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
  return failureCount < 3;
}

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
    defaultOptions: {
      queries: { staleTime: 5_000, refetchOnWindowFocus: false, retry: retryQuery },
      // Only a mutation that opts into `retry` uses this: 0.5 s, then 1 s.
      mutations: { retryDelay: (attempt) => (attempt === 0 ? 500 : 1000) },
    },
    queryCache: new QueryCache({ onError: endSessionOn401 }),
    mutationCache: new MutationCache({ onError: endSessionOn401 }),
  });
  return queryClient;
}
