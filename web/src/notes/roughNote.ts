import { queryOptions, useMutation } from "@tanstack/react-query";
import { api } from "../api/client";
import { ApiError, unwrap } from "../api/errors";
import { pollDelay } from "./draft";

export const MAX_CHARACTERS = 4000;
const SHOW_COUNT_WITHIN = 200;

/** Code points, which is how the server counts (an emoji is one, not two). */
export function countCharacters(text: string): number {
  return Array.from(text).length;
}

/** What the form needs to know about the typed text. Spaces only counts as empty. */
export function textState(text: string) {
  const left = MAX_CHARACTERS - countCharacters(text);
  return {
    left,
    showCount: left <= SHOW_COUNT_WITHIN,
    canSave: text.trim().length > 0 && left >= 0,
  };
}

/** A network error, a timeout or a 5xx: worth sending again with the same key. A 4xx never is. */
export function isTransient(error: unknown): boolean {
  if (error instanceof ApiError) return error.status >= 500;
  if (error instanceof TypeError) return true;
  return error instanceof DOMException && error.name === "TimeoutError";
}

/** Twice, then give up. */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  return failureCount < 2 && isTransient(error);
}

export function useSaveRoughNote(patientId: string, onSent: () => void) {
  return useMutation({
    mutationFn: async ({ text, key }: { text: string; key: string }) =>
      unwrap(
        await api.POST("/api/v1/patients/{patient_id}/rough-notes", {
          params: { path: { patient_id: patientId }, header: { "Idempotency-Key": key } },
          body: { text },
        }),
      ),
    retry: shouldRetry,
    onSuccess: onSent,
  });
}

export const draftJobQuery = (jobId: string) =>
  queryOptions({
    queryKey: ["draft-job", jobId],
    queryFn: async ({ signal }) =>
      unwrap(
        await api.GET("/api/v1/draft-jobs/{job_id}", {
          params: { path: { job_id: jobId } },
          signal,
        }),
      ),
    staleTime: 0,
    // Look again until the job is done, a little less often each time.
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "succeeded" || status === "failed"
        ? false
        : pollDelay(query.state.dataUpdateCount - 1);
    },
  });
