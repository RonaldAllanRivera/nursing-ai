import { QueryCache, QueryClient } from "@tanstack/react-query";
import { ApiError } from "../api/errors";
import { sessionKey } from "../session/session";

/**
 * One per app. Tests build their own with `retry: false`. A 401 from any query means the session
 * is gone: the session query becomes "signed out", and the shell sends you to /sign-in.
 */
export function createQueryClient() {
  const queryClient: QueryClient = new QueryClient({
    defaultOptions: { queries: { staleTime: 5_000, refetchOnWindowFocus: false } },
    queryCache: new QueryCache({
      onError: (error) => {
        if (error instanceof ApiError && error.status === 401) {
          queryClient.setQueryData(sessionKey, null);
        }
      },
    }),
  });
  return queryClient;
}
