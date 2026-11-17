import type { components } from "../api/schema";

type Schemas = components["schemas"];

/** The gates an account (a Google staff member the mock starts signed in as) can start at. */
export type AccountGate = Extract<
  Schemas["SessionGate"],
  "open" | "set_pin" | "enter_pin" | "pin_locked"
>;

/** What a test or a Playwright spec can change about the mock API. Every field is optional. */
export interface MockOptions {
  /** Sign-in options offer Google. Default false: mock mode can't sign in with Google. */
  google?: boolean;
  /** The demo is on: personas, the demo PIN and "reset demo settings". Default true. */
  demo?: boolean;
  /** The gate a persona session starts at. Default "open" until the PIN screen exists. */
  personaGate?: "open" | "enter_pin";
  /**
   * Start signed in as this mock staff member (by id or email). The gate is derived from the user
   * when omitted (PIN locked, no PIN yet, or enter PIN); `"open"` works for an active user with a PIN.
   */
  account?: { user: string; gate?: AccountGate };
  /** The next rough note saved drafts to a failed job with this failure. */
  failDraft?: Schemas["JobFailure"];
}

/** The page global Playwright sets with `page.addInitScript`; the browser's mock reads it once. */
export const MOCK_OPTIONS_GLOBAL = "__SOURCELINE_MOCK__";

const ACCOUNT_GATES: readonly string[] = ["open", "set_pin", "enter_pin", "pin_locked"];
const FAILURES: readonly string[] = [
  "ai_budget_reached",
  "model_refused",
  "invalid_output",
  "provider_error",
  "replay_missing",
];

/**
 * Keeps the well-formed fields of whatever the page global holds and drops the rest: a page can
 * set anything, and a typo must not change the mock's behaviour in ways nobody asked for.
 */
export function readMockOptions(value: unknown): MockOptions {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return {};
  const given = value as Record<string, unknown>;
  const options: MockOptions = {};
  if (typeof given["google"] === "boolean") options.google = given["google"];
  if (typeof given["demo"] === "boolean") options.demo = given["demo"];
  if (given["personaGate"] === "open" || given["personaGate"] === "enter_pin") {
    options.personaGate = given["personaGate"];
  }
  const account = given["account"];
  if (typeof account === "object" && account !== null) {
    const { user, gate } = account as Record<string, unknown>;
    if (typeof user === "string" && user !== "") {
      options.account = { user };
      if (typeof gate === "string" && ACCOUNT_GATES.includes(gate)) {
        options.account.gate = gate as AccountGate;
      }
    }
  }
  if (typeof given["failDraft"] === "string" && FAILURES.includes(given["failDraft"])) {
    options.failDraft = given["failDraft"] as Schemas["JobFailure"];
  }
  return options;
}
