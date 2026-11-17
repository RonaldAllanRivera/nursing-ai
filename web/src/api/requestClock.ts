/**
 * When the app last sent a request that may have restarted the server's idle clock. The server
 * counts every open request as someone being at the screen except the draft-job poll, which runs
 * with nobody there; the browser's idle lock has to wait for the server's count too (it must never
 * lock sooner than the server would, or a PIN would be needed only for the screen while the
 * server still answers). Over-counting only makes the browser lock later, which is safe; missing a
 * request is the bug, so everything the client sends is noted unless it is that poll.
 */
let lastSent: number | null = null;

const DRAFT_JOB_POLL = /^\/api\/v1\/draft-jobs\/[^/]+$/;

/** Whether this request could restart the server's idle clock: all of them but the draft-job poll. */
export function refreshesServerIdle(method: string, path: string): boolean {
  return !(method === "GET" && DRAFT_JOB_POLL.test(path));
}

/** Called by the api client as each request goes out. `path` is the route (a template is fine). */
export function noteRequest(method: string, path: string, now: number = Date.now()) {
  if (refreshesServerIdle(method, path)) lastSent = now;
}

export function lastRefreshingRequest(): number | null {
  return lastSent;
}

/** A new app (and a test) starts with no request sent. */
export function resetRequestClock() {
  lastSent = null;
}
