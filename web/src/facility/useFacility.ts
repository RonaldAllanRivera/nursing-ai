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
export function useFacility(key: string | null) {
  return useQuery({
    ...facilityQuery(key ?? ""),
    enabled: key !== null,
  });
}
