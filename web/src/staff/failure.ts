import { ApiError, isCsrfFailure } from "../api/errors";
import { asksPinAgain, pinProblemMessage } from "../session/pin";

/**
 * What to do about a failed staff action:
 * - `wrong_pin`: the dialog stays and says the tries left;
 * - `gate`: the PIN is locked, and the lock screen replaces the page;
 * - `stale`: the person is gone, or the action is no longer allowed (403/404): the list the
 *   screen showed was out of date, so close the dialog, look at the list again and say so;
 * - `stay`: anything else (no connection, a server error, a stale token): the dialog stays with
 *   its words (`staffFailureWords`) and the person can try again.
 */
export type Failure = "wrong_pin" | "gate" | "stale" | "stay";

export function failureKind(error: unknown): Failure {
  if (asksPinAgain(error)) return "wrong_pin";
  // A stale token is a 403 too, but the list is not what was out of date.
  if (isCsrfFailure(error)) return "stay";
  if (error instanceof ApiError) {
    if (error.status === 423) return "gate";
    if (error.status === 403 || error.status === 404) return "stale";
  }
  return "stay";
}

/** A change refused for a stale token: nothing was changed, and the next try carries a fresh one. */
export const NOT_CHANGED = "That change was not saved. Enter your PIN and try again.";

/** The words a staff PIN dialog shows for a failure that keeps it open. */
export function staffFailureWords(error: unknown): string {
  return isCsrfFailure(error) ? NOT_CHANGED : pinProblemMessage(error, false);
}
