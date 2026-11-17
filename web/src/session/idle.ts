/** The server's idle clock is told of the person at the screen at most this often. */
export const HEARTBEAT_MS = 60_000;

/**
 * Whether the screen has been left alone for `seconds`, and how long until it has. Always judged
 * against the wall clock (`now`), never by counting timer ticks, so a machine that slept or a
 * background tab whose timers were held back still locks on time.
 */
export function idleState(
  lastActivity: number,
  now: number,
  seconds: number,
): { locked: boolean; msLeft: number } {
  const limit = seconds * 1000;
  // A clock that stepped backwards is no reason to lock.
  const idle = Math.max(0, now - lastActivity);
  return idle >= limit ? { locked: true, msLeft: 0 } : { locked: false, msLeft: limit - idle };
}

/** Time to tell the server someone is still here: a full minute since it was last told. */
export function heartbeatDue(lastBeat: number, now: number): boolean {
  return now - lastBeat >= HEARTBEAT_MS;
}
