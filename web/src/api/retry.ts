import { ApiError } from "./errors";
import { isWaking, wakeRetryDelay } from "./waking";

/** TanStack's default (3 retries, so 4 tries), except a 4xx answer: the server meant it, so ask no more. A waking database is waited out instead. */
export function retryQuery(failureCount: number, error: Error): boolean {
  if (isWaking(error)) return wakeRetryDelay(failureCount) !== null;
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
  return failureCount < 3;
}

/** A waking database is asked again every 5 s; anything else backs off like TanStack's default. */
export function queryRetryDelay(failureCount: number, error: Error): number {
  return wakeRetryDelay(failureCount) !== null && isWaking(error)
    ? 5000
    : Math.min(1000 * 2 ** failureCount, 30000);
}

/** The sign-in options query: a 501 (no sign-in on this server yet) stops at once, anything else follows `retryQuery`. */
export function retryOptions(failureCount: number, error: Error): boolean {
  return !(error instanceof ApiError && error.status === 501) && retryQuery(failureCount, error);
}
