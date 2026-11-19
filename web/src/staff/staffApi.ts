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

/** The two changes to one person: the admin ends their access, or clears their PIN. */
export type StaffAction = "revoke" | "reset";

const ROUTES = {
  revoke: "/api/v1/users/{user_id}/revoke",
  reset: "/api/v1/users/{user_id}/pin-reset",
} as const;

/**
 * Revoke someone's access, or reset their PIN, with the actor's PIN. `target` is read when the
 * PIN is sent: who, and which of the two.
 */
export function useStaffAction(
  target: () => { id: string; action: StaffAction },
  handlers: Handlers,
) {
  const queryClient = useQueryClient();
  return usePinRequest(
    async (pin: string) => {
      const { id, action } = target();
      return unwrap(
        await api.POST(ROUTES[action], { params: { path: { user_id: id } }, body: { pin } }),
      );
    },
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
