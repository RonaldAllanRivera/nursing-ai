import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { patchGate } from "./gate";
import { heartbeatDue, idleState } from "./idle";
import { sessionKey, type Session } from "./session";

/** What counts as someone being there. A mouse move alone does not: a passing hand is not use. */
const ACTIVITY = ["pointerdown", "keydown", "wheel", "touchstart"] as const;

/**
 * An unattended screen locks itself. While the session is open, a timer of `idle_lock_seconds` runs
 * from the last click, key press, wheel turn or touch (requests and polls never count, only the
 * person) and, when it runs out, moves the session to the idle gate: the lock screen replaces the
 * page, exactly as if the server had answered 423. Every decision is made against the wall clock
 * (`Date.now()`), so a machine that slept or a tab whose timers were held back locks as soon as
 * anything wakes it, and use that arrives after the limit does not rescue the session.
 *
 * Use also tells the server, at most once a minute, by asking for the session, so the server's own
 * idle clock follows this one. Nothing is ever sent on a timer.
 */
export function useIdleLock(session: Session | null | undefined) {
  const queryClient = useQueryClient();
  const open = session?.gate === "open";
  const seconds = session?.idle_lock_seconds ?? 0;

  useEffect(() => {
    if (!open || seconds <= 0) return;
    let lastActivity = Date.now();
    let lastBeat = lastActivity;
    let timer: ReturnType<typeof setTimeout> | undefined;

    /** Locks if the time is up; otherwise waits for what is left. Returns whether it locked. */
    const check = () => {
      clearTimeout(timer);
      const state = idleState(lastActivity, Date.now(), seconds);
      if (state.locked) {
        patchGate(queryClient, "idle_locked");
        return true;
      }
      timer = setTimeout(check, state.msLeft);
      return false;
    };

    const onActivity = () => {
      if (check()) return;
      const now = Date.now();
      lastActivity = now;
      check();
      if (heartbeatDue(lastBeat, now)) {
        lastBeat = now;
        // The answer refreshes the cached session; a failure here changes nothing and is not shown.
        void queryClient.invalidateQueries({ queryKey: sessionKey });
      }
    };
    const onVisible = () => {
      if (document.visibilityState === "visible") check();
    };

    check();
    for (const name of ACTIVITY) document.addEventListener(name, onActivity, { passive: true });
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearTimeout(timer);
      for (const name of ACTIVITY) document.removeEventListener(name, onActivity);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [open, seconds, queryClient]);
}

/**
 * Sessions are one shared cookie, so another tab can sign in as someone else. Whenever this tab is
 * seen again, ask who the session is now: if it names another person, the cache's identity check
 * drops the last person's data before anything shows it.
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
