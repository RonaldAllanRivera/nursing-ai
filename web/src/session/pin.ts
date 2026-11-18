import { ApiError, SignInRefreshedError } from "../api/errors";
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

/** Said where a PIN is asked for in passing (signing, saving settings) when fewer than six digits were typed. */
export const PIN_NEEDED = "Enter your 6-digit PIN.";

/** A wrong PIN, as opposed to any other way a request that carries a PIN can be refused. */
export function isPinRefusal(error: unknown): boolean {
  return error instanceof ApiError && error.status === 403 && error.problem?.code === "pin_wrong";
}

/** The PIN was not even checked, so no try was used: the sign-in was refreshed under the request. */
export const PIN_NOT_CHECKED =
  "Your sign-in was just refreshed, so the PIN wasn't checked. Enter your PIN again.";

/** A request that asks for the PIN again: a wrong PIN, or one the sign-in refresh kept from being checked. */
export function asksPinAgain(error: unknown): boolean {
  return isPinRefusal(error) || error instanceof SignInRefreshedError;
}

export const PIN_LOCKED = "Your PIN is locked. Ask a head nurse or the admin to reset it.";
/** The locked screen's next step: the session never looks again by itself, so she signs in anew. */
export const PIN_LOCKED_NEXT = "Once it's reset, choose Switch nurse above and sign in again.";
export const PIN_CONNECTION = "Couldn't check your PIN. Check your connection and try again.";
export const PIN_SHORT = "A PIN is 6 digits, 0 to 9.";
export const PINS_DIFFER = "The two PINs don't match.";
export const PIN_CHANGED = "Your sign-in changed in another window. Checking where it stands.";
/** Shown on the sign-in screen after a demo person's fifth wrong PIN ended the session. */
export const DEMO_ENDED =
  "That was the fifth wrong PIN, so the demo session ended. Choose a person to start again.";
/** Shown when a demo session ended for another reason (it ran out while she sat at the PIN screen). */
export const DEMO_EXPIRED = "Your demo session ended. Choose a person to start again.";

/** Shown on the sign-in screen when choosing a first PIN took longer than the session lasted. */
export const PIN_WAIT_ENDED =
  "Choosing your PIN took too long, so you were signed out. Sign in again.";

/**
 * Why a demo session ended when the PIN request answered 401: the fifth wrong PIN only if the try
 * before it was the last one (`tries_left` 1), anything else is a session that ran out. `null`
 * when the failure is not a 401.
 */
export function demoEndedReason(error: unknown, previous: unknown): "fifth" | "expired" | null {
  if (!(error instanceof ApiError) || error.status !== 401) return null;
  const was = previous instanceof ApiError ? previous.problem : undefined;
  return was?.code === "pin_wrong" && was.tries_left === 1 ? "fifth" : "expired";
}

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
  if (error instanceof SignInRefreshedError) return PIN_NOT_CHECKED;
  if (!(error instanceof ApiError)) return PIN_CONNECTION;
  const problem = error.problem;
  if (error.status === 403 && problem?.code === "pin_wrong") {
    const left = problem.tries_left;
    if (typeof left !== "number") return "Wrong PIN.";
    const counted = `Wrong PIN. ${String(left)} ${left === 1 ? "try" : "tries"} left.`;
    if (left !== 1) return counted;
    // The last try: say what one more wrong PIN costs, which depends on who she is.
    return persona
      ? `${counted} Another wrong PIN ends this demo session.`
      : `${counted} Another wrong PIN locks it until a head nurse or the admin resets it.`;
  }
  if (error.status === 423 && problem?.code === "pin_locked") return PIN_LOCKED;
  if (error.status === 409) return PIN_CHANGED;
  if (error.status === 422) {
    const field = problem?.errors?.find((e) => e.field === "body.pin");
    if (field) return field.message;
  }
  return PIN_CONNECTION;
}
