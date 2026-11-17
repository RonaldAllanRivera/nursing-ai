import { useEffect, useRef } from "react";

/**
 * The longest a timer is trusted to sleep. A long `setTimeout` stops counting while the machine
 * sleeps, and not every browser sends `visibilitychange` on waking, so each wait is short and the
 * wall clock is read at the end of it: a late timer costs at most this long.
 */
export const WALL_CLOCK_TICK_MS = 15_000;

/** How long to wait before looking at the clock again, or `null` when the deadline has come. */
export function waitUntil(deadline: number, now: number, tick: number = WALL_CLOCK_TICK_MS) {
  return now >= deadline ? null : Math.min(deadline - now, tick);
}

/**
 * Calls `onReached` once the wall clock passes the deadline, while `active`. `getDeadline` is read
 * at every look (the deadline may move, as the person's activity and requests move it), and a
 * look is made every tick, whenever the tab is seen again and whenever the returned `check` is
 * called. Only the local clock is read: no request is ever sent to check. `check()` says whether
 * the deadline had already come (and so called `onReached`).
 */
export function useWallClockDeadline(
  active: boolean,
  getDeadline: () => number | null,
  onReached: () => void,
): () => boolean {
  const deadline = useRef(getDeadline);
  const reached = useRef(onReached);
  const look = useRef<() => boolean>(() => false);

  // The latest closures, read at each look (declared first so they are current before it runs).
  useEffect(() => {
    deadline.current = getDeadline;
    reached.current = onReached;
  });

  useEffect(() => {
    if (!active) {
      look.current = () => false;
      return;
    }
    let timer: ReturnType<typeof setTimeout> | undefined;
    const check = () => {
      clearTimeout(timer);
      const due = deadline.current();
      if (due === null) return false;
      const wait = waitUntil(due, Date.now());
      if (wait === null) {
        reached.current();
        return true;
      }
      timer = setTimeout(check, wait);
      return false;
    };
    const onVisible = () => {
      if (document.visibilityState === "visible") check();
    };
    look.current = check;
    check();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearTimeout(timer);
      look.current = () => false;
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [active]);

  return () => look.current();
}
