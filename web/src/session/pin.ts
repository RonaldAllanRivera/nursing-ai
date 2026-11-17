import { ApiError } from "../api/errors";
import type { Session } from "./session";

/** Which screen a gate shows. `null` is the open gate: the page itself. */
export type GateScreenName = Exclude<Session["gate"], "open">;

export function screenForGate(gate: Session["gate"]): GateScreenName | null {
  return gate === "open" ? null : gate;
}

export const PIN_LENGTH = 6;

/** A PIN is exactly six digits. The field only ever lets digits in, so this is the length check. */
export function isPinTyped(value: string): boolean {
  return /^[0-9]{6}$/.test(value);
}

export const PIN_LOCKED = "Your PIN is locked. Ask a head nurse or the admin to reset it.";
export const PIN_CONNECTION = "Couldn't check your PIN. Check your connection and try again.";
export const PIN_SHORT = "A PIN is 6 digits, 0 to 9.";
export const PINS_DIFFER = "The two PINs don't match.";
/** Shown on the sign-in screen after a demo person's fifth wrong PIN ended the session. */
export const DEMO_ENDED =
  "That was the fifth wrong PIN, so the demo session ended. Choose a person to start again.";

/** "Locked after 5 minutes without use." from the session's `idle_lock_seconds`. */
export function idleLockWords(seconds: number): string {
  const [count, unit] = seconds < 60 ? [seconds, "second"] : [Math.round(seconds / 60), "minute"];
  return `Locked after ${String(count)} ${unit}${count === 1 ? "" : "s"} without use.`;
}

/**
 * The words for a PIN request that failed. A demo person's last try carries the warning that the
 * next wrong PIN ends the session (her tries count on the session, not on a PIN that can be reset).
 */
export function pinProblemMessage(error: unknown, persona: boolean): string {
  if (!(error instanceof ApiError)) return PIN_CONNECTION;
  const problem = error.problem;
  if (error.status === 403 && problem?.code === "pin_wrong") {
    const left = problem.tries_left;
    if (typeof left !== "number") return "Wrong PIN.";
    const counted = `Wrong PIN. ${String(left)} ${left === 1 ? "try" : "tries"} left.`;
    return persona && left === 1 ? `${counted} Another wrong PIN ends this demo session.` : counted;
  }
  if (error.status === 423 && problem?.code === "pin_locked") return PIN_LOCKED;
  if (error.status === 422) {
    const field = problem?.errors?.find((e) => e.field === "body.pin");
    if (field) return field.message;
  }
  return PIN_CONNECTION;
}
