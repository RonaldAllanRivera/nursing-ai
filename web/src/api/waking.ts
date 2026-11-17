import { ApiError } from "./errors";

/** The server pauses the database when idle; this answer means it is resuming and nothing was written. */
export function isWaking(error: unknown): boolean {
  return (
    error instanceof ApiError && error.status === 503 && error.problem?.code === "database_waking"
  );
}

const WAKE_WAIT_MS = 5000;
const WAKE_TRIES = 12;

/** How long to wait before try number `attempt + 1` (TanStack's `failureCount`): 5 s, twelve times, then give up (`null`). */
export function wakeRetryDelay(attempt: number): number | null {
  return attempt < WAKE_TRIES ? WAKE_WAIT_MS : null;
}
