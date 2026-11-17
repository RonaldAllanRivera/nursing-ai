import { afterEach } from "vitest";
import { api, readSessionFrom } from "../api/client";
import type { Session } from "../session/session";
import { demoApi } from "../mocks/demo-api";

let current: Session | null = null;

// The client reads the CSRF token from here; a test must not leave its session for the next one.
afterEach(() => {
  current = null;
  readSessionFrom(() => undefined);
});

/** Makes the `api` client send the token of this session, as the app does from its cache. */
export function sendTokenOf(session: Session | null) {
  current = session;
  readSessionFrom(() => current);
  return session;
}

/** The demo persona with this role in this facility. */
export function personaId(role: string, facility: string | null) {
  const found = demoApi.personas.find((p) => p.role === role && p.facility_key === facility);
  if (!found) throw new Error(`no ${role} persona`);
  return found.id;
}

/** Signs in as a persona through the mock, and sends that session's token from now on. */
export async function signInAs(role: string, facility: string | null): Promise<Session> {
  const { data } = await api.POST("/api/v1/session", {
    body: { persona_id: personaId(role, facility) },
  });
  if (!data) throw new Error("sign-in failed");
  sendTokenOf(data);
  return data;
}

export interface RawAnswer {
  status: number;
  headers: Headers;
  // The body is whatever the route answered: tests read the fields they expect.
  body: Record<string, unknown> & {
    code?: string;
    tries_left?: number;
    errors?: { field: string }[];
  };
}

/**
 * A request made without the typed client, for tests that need to leave out or swap a header.
 * It sends the current session's token unless `token` says otherwise (`null` sends none).
 */
export async function raw(
  method: string,
  path: string,
  options: { body?: unknown; headers?: Record<string, string>; token?: string | null } = {},
): Promise<RawAnswer> {
  const token = options.token === undefined ? current?.csrf_token : options.token;
  const response = await fetch(`${globalThis.location.origin}${path}`, {
    method,
    headers: {
      ...(options.body === undefined ? {} : { "Content-Type": "application/json" }),
      ...(token ? { "X-CSRF-Token": token } : {}),
      ...options.headers,
    },
    ...(options.body === undefined ? {} : { body: JSON.stringify(options.body) }),
  });
  const text = await response.text();
  return {
    status: response.status,
    headers: response.headers,
    body: text === "" ? {} : (JSON.parse(text) as RawAnswer["body"]),
  };
}

/** Adopts the session the mock started with (the `account` option), as the app would on load. */
export async function adoptSession(): Promise<Session> {
  const { data } = await api.GET("/api/v1/session");
  if (!data) throw new Error("no session");
  sendTokenOf(data);
  return data;
}
