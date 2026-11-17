import type { Problem } from "../api/errors";
import type { Session } from "./session";

export type LockGate = Exclude<Session["gate"], "open">;

const GATES: readonly string[] = ["set_pin", "enter_pin", "idle_locked", "pin_locked"];

/** A 423 names the gate the session is stuck at in its problem code; any other answer names none. */
export function gateFromProblem(problem: Problem | undefined): LockGate | null {
  if (problem?.status !== 423 || !GATES.includes(problem.code)) return null;
  return problem.code as LockGate;
}
