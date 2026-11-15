import { queryOptions, useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { unwrap } from "../api/errors";

export const patientsQuery = queryOptions({
  queryKey: ["patients"],
  queryFn: async ({ signal }) => unwrap(await api.GET("/api/v1/patients", { signal })),
});

export function usePatients() {
  return useQuery(patientsQuery);
}
