import { ApiError } from "../api/errors";
import { isPinRefusal } from "../session/pin";

/**
 * What to do about a failed staff action:
 * - `wrong_pin`: the dialog stays and says the tries left;
 * - `gate`: the PIN is locked, and the lock screen replaces the page;
 * - `stale`: the person is gone, or the action is no longer allowed (403/404): the list the
 *   screen showed was out of date, so close the dialog, look at the list again and say so;
 * - `stay`: anything else (no connection, a server error): the dialog stays with its connection
 *   words and the person can try again.
 */
export type Failure = "wrong_pin" | "gate" | "stale" | "stay";

export function failureKind(error: unknown): Failure {
  if (isPinRefusal(error)) return "wrong_pin";
  if (error instanceof ApiError) {
    if (error.status === 423) return "gate";
    if (error.status === 403 || error.status === 404) return "stale";
  }
  return "stay";
}
