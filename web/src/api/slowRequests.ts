import { useSyncExternalStore } from "react";

/** A request still waiting after this long is "slow": the screen says the demo is waking. */
export const SLOW_AFTER_MS = 5_000;

let slow = 0;
const listeners = new Set<() => void>();

function change(by: number) {
  slow += by;
  listeners.forEach((listener) => {
    listener();
  });
}

/**
 * Called by the api client as a request goes out; returns what to call when it settles. The server
 * holds a request while the database resumes (it answers 503 only after 20 s), so a long wait
 * must not be silent.
 */
export function trackSlowRequest(): () => void {
  let counted = false;
  const timer = setTimeout(() => {
    counted = true;
    change(1);
  }, SLOW_AFTER_MS);
  return () => {
    clearTimeout(timer);
    if (counted) change(-1);
    counted = false;
  };
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** How many requests have been pending for more than 5 s. */
export function useSlowRequests(): number {
  return useSyncExternalStore(subscribe, () => slow);
}
