import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { isPastExpiry } from "./expiry";
import { sessionKey } from "./session";

/**
 * The session's hard limit (`expires_at`, which an unlock never extends). At that instant the
 * session is over whatever screen is up: the cached session becomes "signed out" and the cache's
 * identity check drops the person's data and leaves the reason for the sign-in screen. A long
 * timer can be late or skipped while the machine sleeps, so the clock is read again when the timer
 * fires and whenever the tab is seen again.
 */
export function useSessionExpiry(expiresAt: string | undefined) {
  const queryClient = useQueryClient();
  useEffect(() => {
    if (expiresAt === undefined || Number.isNaN(Date.parse(expiresAt))) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const check = () => {
      clearTimeout(timer);
      if (isPastExpiry(expiresAt, Date.now())) {
        queryClient.setQueryData(sessionKey, null);
        return;
      }
      // A timer's longest wait is about 24 days; a session is hours, but stay inside it anyway.
      timer = setTimeout(check, Math.min(Date.parse(expiresAt) - Date.now(), 2 ** 31 - 1));
    };
    const onVisible = () => {
      if (document.visibilityState === "visible") check();
    };
    check();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [expiresAt, queryClient]);
}
