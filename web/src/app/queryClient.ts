import { QueryClient } from "@tanstack/react-query";

/** One per app. Tests build their own with `retry: false`. */
export function createQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { staleTime: 5_000, refetchOnWindowFocus: false } },
  });
}
