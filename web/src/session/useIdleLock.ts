import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { lastRefreshingRequest } from "../api/requestClock";
import { patchGate } from "./gate";
import { heartbeatDue, idleDeadline } from "./idle";
import { sessionKey, type Session } from "./session";
import { useWallClockDeadline } from "./useWallClockDeadline";

/** What counts as someone being there. A mouse move alone does not: a passing hand is not use. */
const ACTIVITY = ["pointerdown", "keydown", "wheel", "touchstart"] as const;

/**
 * An unattended screen locks itself. While the session is open, the screen locks `idle_lock_seconds`
 * after the last click, key press, wheel turn or touch, moving the session to the idle gate: the
 * lock screen replaces the page, exactly as if the server had answered 423. It never locks before
 * the server would: a request that may restart the server's idle clock (every one but the draft
 * poll) moves the deadline too (see `idleDeadline`), so a PIN is never asked of the screen while
 * the server still answers. The wall clock decides (see `useWallClockDeadline`), and activity that
 * arrives after the deadline does not rescue the session.
 *
 * Use also tells the server, at most once a minute and only while the session is open, by asking
 * for the session, so the server's idle clock follows this one. Nothing is ever sent on a timer.
 */
export function useIdleLock(session: Session | null | undefined) {
  const queryClient = useQueryClient();
  const open = session?.gate === "open";
  const seconds = session?.idle_lock_seconds ?? 0;
  const lastActivity = useRef(0);
  const lastBeat = useRef(0);

  // A new open session (first load, or after an unlock) starts a full count. Declared before the
  // clock's own effect, which reads these when it starts.
  useEffect(() => {
    if (!open) return;
    lastActivity.current = Date.now();
    lastBeat.current = lastActivity.current;
  }, [open]);

  const check = useWallClockDeadline(
    open && seconds > 0,
    () => idleDeadline(lastActivity.current, Date.now(), seconds, lastRefreshingRequest()),
    () => {
      patchGate(queryClient, "idle_locked");
    },
  );

  useEffect(() => {
    if (!open || seconds <= 0) return;
    const onActivity = () => {
      if (check()) return;
      const now = Date.now();
      lastActivity.current = now;
      if (heartbeatDue(lastBeat.current, now)) {
        lastBeat.current = now;
        // The answer refreshes the cached session; a failure here changes nothing and is not shown.
        void queryClient.invalidateQueries({ queryKey: sessionKey });
      }
      // The deadline moved: look again (this restarts the wait from what is left).
      check();
    };
    for (const name of ACTIVITY) document.addEventListener(name, onActivity, { passive: true });
    return () => {
      for (const name of ACTIVITY) document.removeEventListener(name, onActivity);
    };
  }, [open, seconds, queryClient, check]);
}

/**
 * Sessions are one shared cookie, so another tab can sign in as someone else. Whenever this tab is
 * seen again, ask who the session is now: if it names another person, the cache's identity check
 * drops the last person's data before anything shows it. At a gate this is also how another
 * window's unlock or reset is noticed. While the session is open the answer restarts the server's
 * idle clock, which the idle lock knows (the client notes every request).
 */
export function useLookAgainWhenSeen(signedIn: boolean) {
  const queryClient = useQueryClient();
  useEffect(() => {
    if (!signedIn) return;
    const onVisible = () => {
      if (document.visibilityState === "visible") {
        void queryClient.invalidateQueries({ queryKey: sessionKey });
      }
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [signedIn, queryClient]);
}
