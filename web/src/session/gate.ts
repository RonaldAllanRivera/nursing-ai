import type { QueryClient } from "@tanstack/react-query";
import type { Problem } from "../api/errors";
import { sessionKey, type Session } from "./session";

export type LockGate = Exclude<Session["gate"], "open">;

const GATES: readonly string[] = ["set_pin", "enter_pin", "idle_locked", "pin_locked"];

/** A 423 names the gate the session is stuck at in its problem code; any other answer names none. */
export function gateFromProblem(problem: Problem | undefined): LockGate | null {
  if (problem?.status !== 423 || !GATES.includes(problem.code)) return null;
  return problem.code as LockGate;
}

/**
 * Moves the cached session to this gate and changes nothing else (the page under it keeps what she
 * typed). The one patch every lock goes through: a server 423 and the browser's own idle timer.
 */
export function patchGate(queryClient: QueryClient, gate: LockGate) {
  queryClient.setQueryData<Session | null>(sessionKey, (session) =>
    session ? { ...session, gate } : session,
  );
}
