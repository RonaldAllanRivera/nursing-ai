import { queryOptions, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { unwrap } from "../api/errors";
import type { components } from "../api/schema";
import { usePinRequest } from "../session/usePinRequest";
import { inviteBody, type InviteValues } from "./invite";

export type StaffRow = components["schemas"]["UserOut"];

/** Who the actor may see: everyone for the admin, her facility for a head nurse. */
export const staffQuery = queryOptions({
  queryKey: ["staff"],
  queryFn: async ({ signal }) => unwrap(await api.GET("/api/v1/users", { signal })),
});

/** An answer is the new truth about that person: put it in the list in place of the old row. */
function keepRow(queryClient: QueryClient, row: StaffRow) {
  queryClient.setQueryData<StaffRow[]>(staffQuery.queryKey, (rows) =>
    rows?.map((r) => (r.id === row.id ? row : r)),
  );
}

interface Handlers {
  onSuccess: (row: StaffRow) => void;
  onError: (error: unknown) => void;
}

/** The admin ends someone's access, with their PIN. `who` is read when the PIN is sent. */
export function useRevoke(who: () => string, handlers: Handlers) {
  const queryClient = useQueryClient();
  return usePinRequest(
    async (pin: string) =>
      unwrap(
        await api.POST("/api/v1/users/{user_id}/revoke", {
          params: { path: { user_id: who() } },
          body: { pin },
        }),
      ),
    {
      onSuccess: (row) => {
        keepRow(queryClient, row);
        handlers.onSuccess(row);
      },
      onError: handlers.onError,
    },
  );
}

/** The admin or a head nurse clears someone's PIN, with their own PIN. */
export function useResetPin(who: () => string, handlers: Handlers) {
  const queryClient = useQueryClient();
  return usePinRequest(
    async (pin: string) =>
      unwrap(
        await api.POST("/api/v1/users/{user_id}/pin-reset", {
          params: { path: { user_id: who() } },
          body: { pin },
        }),
      ),
    {
      onSuccess: (row) => {
        keepRow(queryClient, row);
        handlers.onSuccess(row);
      },
      onError: handlers.onError,
    },
  );
}

/** The admin invites someone, with their PIN. `values` is read when the PIN is sent. */
export function useInvite(values: () => InviteValues, handlers: Handlers) {
  const queryClient = useQueryClient();
  return usePinRequest(
    async (pin: string) =>
      unwrap(await api.POST("/api/v1/users", { body: inviteBody(values(), pin) })),
    {
      onSuccess: (row) => {
        queryClient.setQueryData<StaffRow[]>(staffQuery.queryKey, (rows) =>
          rows ? [...rows, row] : [row],
        );
        handlers.onSuccess(row);
      },
      onError: handlers.onError,
    },
  );
}
