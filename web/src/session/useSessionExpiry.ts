import { useQueryClient } from "@tanstack/react-query";
import { sessionKey } from "./session";
import { useWallClockDeadline } from "./useWallClockDeadline";

/**
 * The session's hard limit (`expires_at`, which an unlock never extends). At that instant the
 * session is over whatever screen is up: the cached session becomes "signed out" and the cache's
 * identity check drops the person's data and leaves the reason for the sign-in screen. The wall
 * clock decides, a few seconds at a time, so a sleeping machine ends the session on waking.
 */
export function useSessionExpiry(expiresAt: string | undefined) {
  const queryClient = useQueryClient();
  const at = expiresAt === undefined ? Number.NaN : Date.parse(expiresAt);
  useWallClockDeadline(
    !Number.isNaN(at),
    () => at,
    () => {
      queryClient.setQueryData(sessionKey, null);
    },
  );
}
