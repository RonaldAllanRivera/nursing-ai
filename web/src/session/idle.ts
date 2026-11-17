/** The server's idle clock is told of the person at the screen at most this often. */
export const HEARTBEAT_MS = 60_000;

/** The browser waits this long past the server's own deadline, so it never locks first. */
export const SERVER_SLACK_MS = 5_000;

/**
 * Whether the screen should lock now, and how long until it should. Judged against the wall clock
 * (`now`), never by counting timer ticks, so a machine that slept still locks on time.
 *
 * Two clocks count. The person's: `seconds` after the last click or key. The server's: `seconds`
 * after the last request that restarted its idle clock (`lastRequest`), which the browser cannot
 * see end, so it waits a little longer than that. The later of the two wins: while the server
 * would still answer, a browser lock protects nothing (a reload would fetch the patient again),
 * and a lock that lifts without the PIN is worse than a late one.
 */
export function idleDeadline(
  lastActivity: number,
  now: number,
  seconds: number,
  lastRequest: number | null = null,
): number {
  const limit = seconds * 1000;
  // A clock that stepped backwards is no reason to lock: the last activity counts as just now.
  const own = Math.min(lastActivity, now) + limit;
  // The same for a request: if the clock stepped back after it, the server may still have stamped
  // it, so it counts as having just happened rather than not at all.
  const server = lastRequest !== null ? Math.min(lastRequest, now) + limit + SERVER_SLACK_MS : 0;
  return Math.max(own, server);
}

export function idleState(
  lastActivity: number,
  now: number,
  seconds: number,
  lastRequest: number | null = null,
): { locked: boolean; msLeft: number } {
  const deadline = idleDeadline(lastActivity, now, seconds, lastRequest);
  return now >= deadline ? { locked: true, msLeft: 0 } : { locked: false, msLeft: deadline - now };
}

/** Time to tell the server someone is still here: a full minute since it was last told. */
export function heartbeatDue(lastBeat: number, now: number): boolean {
  return now - lastBeat >= HEARTBEAT_MS;
}
