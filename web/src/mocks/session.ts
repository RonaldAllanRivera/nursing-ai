import type { components } from "../api/schema";
import type { MockOptions } from "./options";
import { DEMO_PIN, isPinFormat, PIN_FORMAT_MESSAGE } from "./pin";
import { fieldProblem, problem } from "./problems";
import type { MockUser } from "./staff";
import type { DemoApi } from "./types";

type Schemas = components["schemas"];
type SessionOut = Schemas["SessionOut"];
type Gate = Schemas["SessionGate"];

/** Five wrong tries lock a Google user's PIN and end a persona's session. */
const TRIES = 5;
const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

/** Who is signed in and what the server keeps about the session. */
interface Active {
  kind: "persona" | "google";
  userId: string;
  gate: Gate;
  csrf: string;
  expiresAt: string;
  /** A persona's wrong tries count here, on the session; a Google user's count on the user. */
  failures: number;
  shiftOverride: Schemas["ShiftRef"] | null;
}

export type Guarded =
  { refusal: Response; session?: never } | { refusal?: never; session: SessionOut };

/**
 * The mock's session: who is signed in, at which gate, with which CSRF token, and the checks every
 * route makes before its own. There is no idle clock here: the browser's timer drives the lock.
 */
export function createSession(data: DemoApi, options: MockOptions, staff: MockUser[]) {
  let active: Active | null = null;
  let tokens = 0;

  const facilityOf = (key: string | null) => (key === null ? undefined : data.facilities[key]);
  const staffOf = (id: string) => staff.find((u) => u.id === id);
  const expiry = (key: string | null) => {
    const hours = facilityOf(key)?.profile.session_max_hours ?? 12;
    return new Date(Date.now() + hours * 3_600_000).toISOString();
  };
  const nextToken = () => {
    tokens += 1;
    return `mock-csrf-${String(tokens)}`;
  };

  /** A nurse's shift is found by its code in her facility's current shifts: a rename shows at once. */
  const relabelled = (key: string | null, shift: Schemas["ShiftRef"]): Schemas["ShiftRef"] => {
    const label = facilityOf(key)?.profile.shifts.find((s) => s.code === shift.code)?.label;
    return label === undefined ? shift : { ...shift, label };
  };

  /** The session as the API answers it, or undefined when nobody is signed in. */
  function session(): SessionOut | undefined {
    if (!active) return undefined;
    const base =
      active.kind === "persona" ? data.sessions[active.userId] : googleBase(active.userId);
    if (!base) return undefined;
    const shift = active.shiftOverride ?? base.shift;
    return {
      ...base,
      shift: shift ? relabelled(base.facility_key, shift) : null,
      kind: active.kind,
      gate: active.gate,
      csrf_token: active.csrf,
      expires_at: active.expiresAt,
    };
  }

  function googleBase(id: string): SessionOut | undefined {
    const found = staffOf(id);
    if (!found) return undefined;
    return {
      user_id: found.id,
      display_name: found.display_name,
      initials: found.initials,
      role: found.role,
      facility_key: found.facility_key,
      shift: facilityOf(found.facility_key)?.shift_choices[0] ?? null,
      kind: "google",
      gate: "open",
      csrf_token: "",
      expires_at: "",
      idle_lock_seconds: 300,
    };
  }

  function startPersona(personaId: string) {
    const found = data.sessions[personaId];
    if (!found) return undefined;
    active = {
      kind: "persona",
      userId: personaId,
      gate: options.personaGate ?? "open",
      csrf: nextToken(),
      expiresAt: expiry(found.facility_key),
      failures: 0,
      shiftOverride: null,
    };
    return session();
  }

  // The `account` option: start already signed in as a mock staff member.
  if (options.account) {
    const wanted = options.account.user.toLowerCase();
    const found = staff.find((u) => u.id === options.account?.user || u.email === wanted);
    if (found) {
      const gate = options.account.gate ?? "open";
      if (gate === "pin_locked") found.pin_locked = true;
      active = {
        kind: "google",
        userId: found.id,
        gate,
        csrf: nextToken(),
        expiresAt: expiry(found.facility_key),
        failures: 0,
        shiftOverride: null,
      };
    }
  }

  /** The checks before any route's own: signed in (401), then for a change the token (403). */
  function guardSession(request: Request): Guarded {
    const current = session();
    if (!current || !active) return { refusal: problem(401, "not_signed_in") };
    if (UNSAFE.has(request.method) && request.headers.get("X-CSRF-Token") !== active.csrf) {
      return { refusal: problem(403, "csrf_failed") };
    }
    return { session: current };
  }

  /** Every data route: the session checks, then 423 with the gate unless the session is open. */
  function guard(request: Request): Guarded {
    const checked = guardSession(request);
    if (checked.refusal) return checked;
    const gate = checked.session.gate;
    return gate === "open" ? checked : { refusal: problem(423, gate) };
  }

  /**
   * Checks a PIN sent to prove who is at the keyboard. A wrong one counts: a Google user's count
   * on the user (the fifth locks the PIN), a persona's on the session (the fifth ends it).
   * Returns the refusal, or null when the PIN is right.
   */
  function checkPin(pin: unknown): Response | null {
    if (!active) return problem(401, "not_signed_in");
    if (!isPinFormat(pin)) return fieldProblem("body.pin", PIN_FORMAT_MESSAGE);
    const google = active.kind === "google" ? staffOf(active.userId) : undefined;
    if ((google ? google.pin : DEMO_PIN) === pin) {
      if (google) google.failures = 0;
      active.failures = 0;
      return null;
    }
    if (google) {
      google.failures += 1;
      if (google.failures >= TRIES) {
        google.pin_locked = true;
        active.gate = "pin_locked";
        return problem(423, "pin_locked");
      }
      return problem(403, "pin_wrong", undefined, undefined, TRIES - google.failures);
    }
    active.failures += 1;
    if (active.failures >= TRIES) {
      active = null;
      return problem(401, "not_signed_in");
    }
    return problem(403, "pin_wrong", undefined, undefined, TRIES - active.failures);
  }

  return {
    session,
    startPersona,
    guardSession,
    guard,
    checkPin,
    /** The signed-in Google staff member, for the rules that depend on who they are. */
    google: () => (active?.kind === "google" ? staffOf(active.userId) : undefined),
    end: () => {
      active = null;
    },
    setGate: (gate: Gate) => {
      if (active) active.gate = gate;
    },
    setShift: (choice: Schemas["ShiftRef"]) => {
      if (active) active.shiftOverride = choice;
    },
    shift: () => active?.shiftOverride ?? null,
  };
}

export type MockSession = ReturnType<typeof createSession>;
