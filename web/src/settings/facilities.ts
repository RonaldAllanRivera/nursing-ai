import { queryOptions, useQueryClient, type QueryClient } from "@tanstack/react-query";
import type { components } from "../api/schema";
import { api, type FacilitySettings } from "../api/client";
import { unwrap } from "../api/errors";
import { usePinRequest } from "../session/usePinRequest";

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

export interface SavedFacility {
  facility: components["schemas"]["FacilityOut"];
  etag: string | null;
}

/** A facility answer is the new truth: keep it, and let every screen that reads the facility look again. */
function keepFacility(queryClient: QueryClient, key: string, saved: SavedFacility) {
  queryClient.setQueryData(facilitySettingsQuery(key).queryKey, saved);
  // Every screen that reads the facility (the nurse's header, words, clock) sees the change.
  void queryClient.invalidateQueries({ queryKey: ["facility", key] });
  void queryClient.invalidateQueries({ queryKey: facilityListQuery.queryKey });
}

/**
 * Save one facility's settings with the PIN the admin typed, against the version the form was
 * loaded from. `request` is read when the PIN is sent: the settings and the version being saved.
 */
export function useSaveFacility(
  key: string,
  request: () => { etag: string | null; body: FacilitySettings },
  handlers: {
    onSuccess: (saved: SavedFacility) => void;
    onError: (error: unknown, previous: unknown) => void;
  },
) {
  const queryClient = useQueryClient();
  return usePinRequest(
    async (pin: string) => {
      const { etag, body } = request();
      const answer = await api.PUT("/api/v1/facilities/{facility_key}", {
        params: { path: { facility_key: key }, header: { "If-Match": etag } },
        body: { ...body, pin },
      });
      return { facility: unwrap(answer), etag: answer.response.headers.get("ETag") };
    },
    {
      onSuccess: (saved) => {
        keepFacility(queryClient, key, saved);
        handlers.onSuccess(saved);
      },
      onError: handlers.onError,
    },
    // A reload under way would answer with the version from before this save.
    {
      onMutate: () => queryClient.cancelQueries({ queryKey: facilitySettingsQuery(key).queryKey }),
    },
  );
}

/** The demo admin puts a facility's settings back to its preset, with the PIN, against the version on screen. */
export function useResetFacility(
  key: string,
  etag: () => string | null,
  handlers: {
    onSuccess: (saved: SavedFacility) => void;
    onError: (error: unknown, previous: unknown) => void;
  },
) {
  const queryClient = useQueryClient();
  return usePinRequest(
    async (pin: string) => {
      const answer = await api.POST("/api/v1/facilities/{facility_key}/reset", {
        params: { path: { facility_key: key }, header: { "If-Match": etag() } },
        body: { pin },
      });
      return { facility: unwrap(answer), etag: answer.response.headers.get("ETag") };
    },
    {
      onSuccess: (saved) => {
        keepFacility(queryClient, key, saved);
        handlers.onSuccess(saved);
      },
      onError: handlers.onError,
    },
    {
      onMutate: () => queryClient.cancelQueries({ queryKey: facilitySettingsQuery(key).queryKey }),
    },
  );
}
