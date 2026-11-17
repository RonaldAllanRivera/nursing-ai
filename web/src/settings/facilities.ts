import { queryOptions, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type FacilitySettings } from "../api/client";
import { unwrap } from "../api/errors";
import { INTERIM_PIN } from "../session/interimPin";

/** Every facility, for the picker (the admin's list). */
export const facilityListQuery = queryOptions({
  queryKey: ["facilities"],
  queryFn: async ({ signal }) => unwrap(await api.GET("/api/v1/facilities", { signal })),
});

/**
 * One facility's settings and its ETag. The form holds what the admin is typing, so this is
 * never refetched behind it (no staleness, no refocus refetch): the form asks when it wants the
 * latest (Reload settings).
 */
export const facilitySettingsQuery = (key: string) =>
  queryOptions({
    queryKey: ["facility-settings", key],
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    queryFn: async ({ signal }) => {
      const answer = await api.GET("/api/v1/facilities/{facility_key}", {
        params: { path: { facility_key: key } },
        signal,
      });
      return { facility: unwrap(answer), etag: answer.response.headers.get("ETag") };
    },
  });

/** Save one facility's settings against the version the form was loaded from. */
export function useSaveFacility(key: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ etag, body }: { etag: string | null; body: FacilitySettings }) => {
      const answer = await api.PUT("/api/v1/facilities/{facility_key}", {
        params: { path: { facility_key: key }, header: { "If-Match": etag } },
        body: { ...body, pin: INTERIM_PIN },
      });
      return { facility: unwrap(answer), etag: answer.response.headers.get("ETag") };
    },
    // A reload under way would answer with the version from before this save.
    onMutate: () => queryClient.cancelQueries({ queryKey: facilitySettingsQuery(key).queryKey }),
    onSuccess: (saved) => {
      queryClient.setQueryData(facilitySettingsQuery(key).queryKey, saved);
      // Every screen that reads the facility (the nurse's header, words, clock) sees the change.
      void queryClient.invalidateQueries({ queryKey: ["facility", key] });
      void queryClient.invalidateQueries({ queryKey: facilityListQuery.queryKey });
    },
  });
}
