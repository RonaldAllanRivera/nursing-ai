import { queryOptions, useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { unwrap } from "../api/errors";

export const facilityQuery = (key: string) =>
  queryOptions({
    queryKey: ["facility", key],
    queryFn: async ({ signal }) =>
      unwrap(
        await api.GET("/api/v1/facilities/{facility_key}", {
          params: { path: { facility_key: key } },
          signal,
        }),
      ),
  });

/** The facility's profile and shift choices. Locale, clock and timezone come from here, nowhere else. */
export function useFacility(key: string | null, gateOpen = true) {
  return useQuery({
    ...facilityQuery(key ?? ""),
    // Not asked for behind a gate: the server answers 423 until the PIN is proved. The key stays,
    // so the loaded facility is kept (the session hours) while a lock screen is up.
    enabled: key !== null && gateOpen,
  });
}
