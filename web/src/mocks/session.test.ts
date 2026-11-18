import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { adoptSession, raw, signInAs, signInLocked } from "../test/mockSession";
import { server } from "../test/setup";
import { demoApi } from "./demo-api";
import { createHandlers } from "./handlers";
import type { MockOptions } from "./options";
import { MOCK_EMAILS, MOCK_PIN } from "./staff";

const DEMO_PIN = "135790";
const NOTE = Object.keys(demoApi.notes)[0] ?? "";
const PATIENT = demoApi.patients["ph-demo"][0]?.id ?? "";
const ID = "00000000-0000-4000-8000-0000000000aa";

const start = (options?: MockOptions) => {
  server.use(...createHandlers(demoApi, options));
};
const head = (gate: "open" | "set_pin" | "enter_pin" | "pin_locked"): MockOptions => ({
  account: { user: MOCK_EMAILS.phHead, gate },
});
const nurse = (gate: "open" | "set_pin" | "enter_pin" | "pin_locked"): MockOptions => ({
  account: { user: MOCK_EMAILS.phStaff, gate },
});
/** A person with no PIN yet: the only one who can be at set_pin. */
const newcomer: MockOptions = { account: { user: MOCK_EMAILS.phInvited, gate: "set_pin" } };
const unlock = (pin: string) => raw("POST", "/api/v1/session/unlock", { body: { pin } });

const DATA_ROUTES: [string, string, unknown?][] = [
  ["GET", "/api/v1/facilities"],
  ["GET", "/api/v1/facilities/ph-demo"],
  ["PUT", "/api/v1/facilities/ph-demo", {}],
  ["POST", "/api/v1/facilities/ph-demo/reset", { pin: DEMO_PIN }],
  ["PUT", "/api/v1/session/shift", { starts_at: "2026-11-11T14:00:00Z" }],
  ["GET", "/api/v1/patients"],
  ["GET", `/api/v1/patients/${PATIENT}`],
  ["POST", `/api/v1/patients/${PATIENT}/rough-notes`, { text: "x" }],
  ["GET", `/api/v1/draft-jobs/${ID}`],
  ["GET", `/api/v1/notes/${NOTE}`],
  ["PATCH", `/api/v1/notes/${NOTE}/lines/e1-F`, { action: "confirm" }],
  ["POST", `/api/v1/notes/${NOTE}/sign`, { pin: DEMO_PIN }],
  ["POST", `/api/v1/notes/${NOTE}/discard`],
  ["GET", "/api/v1/users"],
  ["POST", "/api/v1/users", {}],
  ["POST", `/api/v1/users/${ID}/revoke`, { pin: DEMO_PIN }],
  ["POST", `/api/v1/users/${ID}/pin-reset`, { pin: DEMO_PIN }],
  ["POST", `/api/v1/rough-notes/${ID}/draft-jobs`],
];

describe("the session gates", () => {
  describe.each(["set_pin", "enter_pin", "pin_locked"] as const)("at %s", (gate) => {
    it.each(DATA_ROUTES)("%s %s answers 423 with the gate", async (method, path, body) => {
      start(gate === "set_pin" ? newcomer : head(gate));
      await adoptSession();
      const answer = await raw(method, path, { body });
      expect(answer.status).toBe(423);
      expect(answer.body.code).toBe(gate);
    });

    it("still answers GET and DELETE /session", async () => {
      start(gate === "set_pin" ? newcomer : head(gate));
      const session = await adoptSession();
      expect(session.gate).toBe(gate);
      expect(session.kind).toBe("google");
      expect((await raw("DELETE", "/api/v1/session")).status).toBe(204);
      expect((await raw("GET", "/api/v1/session")).status).toBe(401);
    });
  });

  it("starts a persona session at enter_pin by default, as the server does", async () => {
    start();
    const session = await signInLocked("staff_nurse", "ph-demo");
    expect(session.gate).toBe("enter_pin");
    expect((await raw("GET", "/api/v1/patients")).body.code).toBe("enter_pin");
  });

  it("starts personas open when the option says so", async () => {
    start({ personaGate: "open" });
    expect((await signInLocked("staff_nurse", "ph-demo")).gate).toBe("open");
  });

  it("answers 401 before CSRF and CSRF before the gate", async () => {
    start();
    expect((await raw("POST", `/api/v1/notes/${NOTE}/discard`, { token: null })).status).toBe(401);
    start(head("enter_pin"));
    await adoptSession();
    const refused = await raw("POST", `/api/v1/notes/${NOTE}/discard`, { token: null });
    expect([refused.status, refused.body.code]).toEqual([403, "csrf_failed"]);
  });
});

describe("CSRF", () => {
  it("refuses an unsafe request with no token or the wrong one", async () => {
    start();
    await signInAs("staff_nurse", "ph-demo");
    for (const token of [null, "mock-csrf-wrong"]) {
      const answer = await raw("POST", `/api/v1/notes/${NOTE}/discard`, { token });
      expect([answer.status, answer.body.code]).toEqual([403, "csrf_failed"]);
    }
  });

  it("refuses another session's token", async () => {
    start();
    const first = await signInAs("staff_nurse", "ph-demo");
    const second = await signInAs("staff_nurse", "ph-demo");
    expect(second.csrf_token).not.toBe(first.csrf_token);
    expect(first.csrf_token).toMatch(/^mock-csrf-\d+$/);
    const answer = await raw("PUT", "/api/v1/session/shift", {
      body: { starts_at: "2026-11-11T14:00:00Z" },
      token: first.csrf_token,
    });
    expect(answer.body.code).toBe("csrf_failed");
  });

  it("needs none for a GET, and none to start a session", async () => {
    start();
    await signInAs("staff_nurse", "ph-demo");
    expect((await raw("GET", "/api/v1/patients", { token: null })).status).toBe(200);
    const again = await raw("POST", "/api/v1/session", {
      body: { persona_id: demoApi.personas[0]?.id },
      token: null,
    });
    expect(again.status).toBe(201);
  });

  it("holds DELETE /session and the PIN routes to it too", async () => {
    start(newcomer);
    await adoptSession();
    const pin = await raw("POST", "/api/v1/session/pin", { body: { pin: MOCK_PIN }, token: null });
    expect(pin.body.code).toBe("csrf_failed");
    const unlocked = await raw("POST", "/api/v1/session/unlock", {
      body: { pin: MOCK_PIN },
      token: null,
    });
    expect(unlocked.body.code).toBe("csrf_failed");
    const out = await raw("DELETE", "/api/v1/session", { token: null });
    expect(out.body.code).toBe("csrf_failed");
    expect((await raw("DELETE", "/api/v1/session")).status).toBe(204);
  });
});

describe("sign-in options and sessions", () => {
  it("follow the options", async () => {
    start();
    const plain = await raw("GET", "/api/v1/sign-in-options");
    expect(plain.body).toEqual({
      google: false,
      personas: true,
      demo: true,
      demo_pin: DEMO_PIN,
    });
    start({ google: true, demo: false });
    const other = await raw("GET", "/api/v1/sign-in-options");
    expect(other.body).toEqual({ google: true, personas: true, demo: false, demo_pin: null });
  });

  it("gives a persona session the facility's length and its own token", async () => {
    start();
    const hours = async (role: string, facility: string | null) => {
      const session = await signInAs(role, facility);
      return [session, (Date.parse(session.expires_at) - Date.now()) / 3_600_000] as const;
    };
    const [ph, phHours] = await hours("staff_nurse", "ph-demo");
    const [us, usHours] = await hours("head_nurse", "us-demo");
    const [admin, adminHours] = await hours("admin", null);
    expect([phHours, usHours, adminHours].map((h) => Math.round(h))).toEqual([12, 14, 12]);
    expect(new Set([ph.csrf_token, us.csrf_token, admin.csrf_token]).size).toBe(3);
    expect([ph.kind, ph.idle_lock_seconds]).toEqual(["persona", 300]);
  });
});

describe("POST /session/pin", () => {
  const set = (pin: string) => raw("POST", "/api/v1/session/pin", { body: { pin } });

  it("refuses a malformed or weak PIN with a field error on body.pin", async () => {
    start(newcomer);
    await adoptSession();
    for (const pin of ["12345", "1234567", "12345a", "١٢٣٤٥٦", ""]) {
      const answer = await set(pin);
      expect([answer.status, answer.body.errors?.[0]?.field]).toEqual([422, "body.pin"]);
    }
    for (const pin of ["000000", "111111", "123456", "345678", "654321", "987654"]) {
      const answer = await set(pin);
      expect([answer.status, answer.body.errors?.[0]?.field]).toEqual([422, "body.pin"]);
    }
  });

  it("stores a good PIN, opens the session, and refuses a second one", async () => {
    start(newcomer);
    await adoptSession();
    const done = await set(MOCK_PIN);
    expect(done.status).toBe(200);
    expect(done.body["gate"]).toBe("open");
    expect((await raw("GET", "/api/v1/patients")).status).toBe(200);
    const twice = await set("246810");
    expect([twice.status, twice.body.code]).toEqual([409, "pin_already_set"]);
  });

  it("takes the demo PIN as a new PIN", async () => {
    start(newcomer);
    await adoptSession();
    expect((await set(DEMO_PIN)).status).toBe(200);
  });

  it("answers 409 when the gate is not set_pin", async () => {
    start(nurse("enter_pin"));
    await adoptSession();
    expect((await set(MOCK_PIN)).body.code).toBe("pin_already_set");
  });

  it("refuses a weak PIN in the server's own words", async () => {
    start(newcomer);
    await adoptSession();
    const answer = await set("111111");
    expect(answer.body.errors).toEqual([{ field: "body.pin", message: "that PIN is too easy" }]);
  });

  describe("a first PIN chosen after the idle-lock time since the sign-in", () => {
    beforeEach(() => {
      vi.useFakeTimers({ toFake: ["Date"] });
    });
    afterEach(() => {
      vi.useRealTimers();
    });

    it("ends the session with a 401, before a weak PIN is looked at", async () => {
      start(newcomer);
      await adoptSession();
      vi.setSystemTime(Date.now() + 300 * 1000);
      const late = await set("111111");
      expect([late.status, late.body.code]).toEqual([401, "not_signed_in"]);
      expect((await raw("GET", "/api/v1/session")).status).toBe(401);
    });

    it("is taken just under the time, and reading the session does not restart the count", async () => {
      start(newcomer);
      await adoptSession();
      vi.setSystemTime(Date.now() + 150 * 1000);
      expect((await raw("GET", "/api/v1/session")).body["gate"]).toBe("set_pin");
      vi.setSystemTime(Date.now() + 149 * 1000);
      expect((await set(MOCK_PIN)).status).toBe(200);
    });

    it("still answers 409 first when a PIN is already set", async () => {
      start(nurse("enter_pin"));
      await adoptSession();
      vi.setSystemTime(Date.now() + 300 * 1000);
      expect((await set(MOCK_PIN)).body.code).toBe("pin_already_set");
    });
  });
});

describe("POST /session/unlock", () => {
  it("opens a Google session on the right PIN", async () => {
    start(nurse("enter_pin"));
    await adoptSession();
    const answer = await unlock(MOCK_PIN);
    expect([answer.status, answer.body["gate"]]).toEqual([200, "open"]);
  });

  it("counts a Google user's wrong tries down, then locks the PIN and keeps it locked", async () => {
    start(nurse("enter_pin"));
    await adoptSession();
    const left: unknown[] = [];
    for (let i = 0; i < 4; i += 1) {
      const answer = await unlock("999999");
      expect(answer.status).toBe(403);
      expect(answer.body.code).toBe("pin_wrong");
      left.push(answer.body.tries_left);
    }
    expect(left).toEqual([4, 3, 2, 1]);
    const fifth = await unlock("999999");
    expect([fifth.status, fifth.body.code]).toEqual([423, "pin_locked"]);
    expect((await raw("GET", "/api/v1/session")).body["gate"]).toBe("pin_locked");
    const right = await unlock(MOCK_PIN);
    expect([right.status, right.body.code]).toEqual([423, "pin_locked"]);
  });

  it("does not count a malformed PIN", async () => {
    start(nurse("enter_pin"));
    await adoptSession();
    expect((await unlock("12")).status).toBe(422);
    expect((await unlock("999999")).body.tries_left).toBe(4);
  });

  it("clears the failures on a right PIN", async () => {
    start(nurse("enter_pin"));
    await adoptSession();
    await unlock("999999");
    await unlock("999999");
    expect((await unlock(MOCK_PIN)).status).toBe(200);
    // Cleared: the next wrong PIN is the first of five again, not the third.
    const next = await raw("POST", `/api/v1/notes/${NOTE}/sign`, {
      body: { pin: "999999" },
      headers: { "If-Match": '"v1"' },
    });
    expect([next.body.code, next.body.tries_left]).toEqual(["pin_wrong", 4]);
  });

  it("checks the PIN at gate open, as the server does: a right one opens, a wrong one counts", async () => {
    start(nurse("open"));
    await adoptSession();
    const right = await unlock(MOCK_PIN);
    expect([right.status, right.body["gate"]]).toEqual([200, "open"]);
    const wrong = await unlock("999999");
    expect([wrong.status, wrong.body.code, wrong.body.tries_left]).toEqual([403, "pin_wrong", 4]);
    expect((await unlock("999999")).body.tries_left).toBe(3);
  });

  it("answers 423 set_pin at set_pin, as the server does", async () => {
    start(newcomer);
    await adoptSession();
    const answer = await unlock(MOCK_PIN);
    expect([answer.status, answer.body.code]).toEqual([423, "set_pin"]);
  });

  it("ends only a persona's session on the fifth wrong try", async () => {
    start();
    await signInLocked("staff_nurse", "ph-demo");
    const left: unknown[] = [];
    for (let i = 0; i < 4; i += 1) left.push((await unlock("999999")).body.tries_left);
    expect(left).toEqual([4, 3, 2, 1]);
    const fifth = await unlock("999999");
    expect([fifth.status, fifth.body.code]).toEqual([401, "not_signed_in"]);
    expect((await raw("GET", "/api/v1/session")).status).toBe(401);
    const again = await signInLocked("staff_nurse", "ph-demo");
    expect(again.gate).toBe("enter_pin");
    expect((await unlock(DEMO_PIN)).status).toBe(200);
  });
});

describe("a PIN in a write", () => {
  const sign = (pin: string, ifMatch = '"v1"') =>
    raw("POST", `/api/v1/notes/${NOTE}/sign`, { body: { pin }, headers: { "If-Match": ifMatch } });

  it("is checked after If-Match and before the review check", async () => {
    start();
    await signInAs("staff_nurse", "ph-demo");
    expect((await sign("999999", '"v9"')).status).toBe(412);
    const wrong = await sign("999999");
    expect([wrong.status, wrong.body.code, wrong.body.tries_left]).toEqual([403, "pin_wrong", 4]);
    const right = await sign(DEMO_PIN);
    expect([right.status, right.body.code]).toEqual([409, "review_incomplete"]);
    expect((await sign("12")).status).toBe(422);
  });

  it("counts toward the lock: a persona's fifth ends the session", async () => {
    start();
    await signInAs("staff_nurse", "ph-demo");
    for (let i = 0; i < 4; i += 1) await sign("999999");
    const fifth = await sign("999999");
    expect([fifth.status, fifth.body.code]).toEqual([401, "not_signed_in"]);
  });

  it("counts toward the lock: a Google user's fifth locks the PIN", async () => {
    start(nurse("open"));
    await adoptSession();
    for (let i = 0; i < 4; i += 1) await sign("999999");
    const fifth = await sign("999999");
    expect([fifth.status, fifth.body.code]).toEqual([423, "pin_locked"]);
    expect((await raw("GET", "/api/v1/patients")).body.code).toBe("pin_locked");
  });

  it("is checked on a settings save after 412 and before validation", async () => {
    start();
    await signInAs("admin", null);
    const save = (pin: string, ifMatch = '"f1"') =>
      raw("PUT", "/api/v1/facilities/ph-demo", {
        body: { name: "", pin },
        headers: { "If-Match": ifMatch },
      });
    expect((await save("999999", '"f9"')).status).toBe(412);
    const wrong = await save("999999");
    expect([wrong.status, wrong.body.code, wrong.body.tries_left]).toEqual([403, "pin_wrong", 4]);
    expect((await save(DEMO_PIN)).status).toBe(422);
  });
});

describe("POST /facilities/{key}/reset", () => {
  const reset = (ifMatch: string | null, pin = DEMO_PIN) =>
    raw("POST", "/api/v1/facilities/ph-demo/reset", {
      body: { pin },
      headers: ifMatch === null ? {} : { "If-Match": ifMatch },
    });
  const original = demoApi.facilities["ph-demo"];

  it("puts the demo's own settings back, one version on, with the new ETag", async () => {
    start();
    await signInAs("admin", null);
    const profile = { ...original?.profile, name: "Renamed", pin: DEMO_PIN };
    delete (profile as { key?: string }).key;
    const saved = await raw("PUT", "/api/v1/facilities/ph-demo", {
      body: profile,
      headers: { "If-Match": '"f1"' },
    });
    expect(saved.status).toBe(200);
    const back = await reset('"f2"');
    expect(back.status).toBe(200);
    expect(back.headers.get("ETag")).toBe('"f3"');
    expect(back.body["version"]).toBe(3);
    expect((back.body["profile"] as { name: string }).name).toBe(original?.profile.name);
  });

  it("asks for If-Match, refuses a stale one and a wrong PIN", async () => {
    start();
    await signInAs("admin", null);
    expect((await reset(null)).status).toBe(428);
    expect((await reset('"f7"')).status).toBe(412);
    expect((await reset('"f1"', "999999")).body.code).toBe("pin_wrong");
    expect((await reset('"f1"', "12")).status).toBe(422);
    expect((await reset('"f1"')).status).toBe(200);
  });

  it("is for the admin persona only, and only in the demo", async () => {
    start();
    await signInAs("head_nurse", "ph-demo");
    expect((await reset('"f1"')).status).toBe(403);
    start({ demo: false });
    await signInAs("admin", null);
    expect((await reset('"f1"')).status).toBe(403);
  });

  it("answers 404 for a facility that is not there", async () => {
    start();
    await signInAs("admin", null);
    const answer = await raw("POST", "/api/v1/facilities/nowhere/reset", {
      body: { pin: DEMO_PIN },
      headers: { "If-Match": '"f1"' },
    });
    expect(answer.status).toBe(404);
  });
});

describe("the idle clock", () => {
  const IDLE_MS = 300 * 1000;
  const at = (ms: number) => vi.setSystemTime(Date.now() + ms);
  const patients = () => raw("GET", "/api/v1/patients");
  const gateNow = async () => (await raw("GET", "/api/v1/session")).body["gate"];

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("locks a session left alone for the idle time, and says so at GET /session", async () => {
    start();
    await signInAs("staff_nurse", "ph-demo");
    at(IDLE_MS);
    const locked = await patients();
    expect([locked.status, locked.body.code]).toEqual([423, "idle_locked"]);
    expect(await gateNow()).toBe("idle_locked");
  });

  it("reports the lock at GET /session before any data route", async () => {
    start();
    await signInAs("staff_nurse", "ph-demo");
    at(IDLE_MS);
    expect(await gateNow()).toBe("idle_locked");
  });

  it("stays open just under the limit, and a data request starts the count again", async () => {
    start();
    await signInAs("staff_nurse", "ph-demo");
    at(IDLE_MS - 1000);
    expect((await patients()).status).toBe(200);
    at(IDLE_MS - 1000);
    expect((await patients()).status).toBe(200);
  });

  it("is not kept open by polling a draft job", async () => {
    start();
    await signInAs("staff_nurse", "ph-demo");
    for (let i = 0; i < 4; i += 1) {
      at(IDLE_MS / 4);
      await raw("GET", `/api/v1/draft-jobs/${ID}`);
    }
    expect((await patients()).body.code).toBe("idle_locked");
  });

  it("is kept open by GET /session while the session is open", async () => {
    start();
    await signInAs("staff_nurse", "ph-demo");
    for (let i = 0; i < 3; i += 1) {
      at(IDLE_MS - 1000);
      expect(await gateNow()).toBe("open");
    }
    expect((await patients()).status).toBe(200);
  });

  it("answers a wrong PIN at its own idle lock as a wrong PIN, with nothing thrown in a handler", async () => {
    const thrown = vi.spyOn(console, "error").mockImplementation(() => undefined);
    try {
      start();
      await signInAs("staff_nurse", "ph-demo");
      at(IDLE_MS);
      const wrong = await unlock("000000");
      expect([wrong.status, wrong.body.code]).toEqual([403, "pin_wrong"]);
      expect(await gateNow()).toBe("idle_locked");
      expect(thrown).not.toHaveBeenCalled();
    } finally {
      thrown.mockRestore();
    }
  });

  it("opens again on unlock from idle_locked, for a persona and a Google user", async () => {
    start();
    await signInAs("staff_nurse", "ph-demo");
    at(IDLE_MS);
    expect((await unlock(DEMO_PIN)).body["gate"]).toBe("open");
    expect((await patients()).status).toBe(200);
    start(nurse("open"));
    await adoptSession();
    at(IDLE_MS);
    expect((await unlock(MOCK_PIN)).status).toBe(200);
    at(IDLE_MS - 1000);
    expect((await patients()).status).toBe(200);
  });
});

describe("the account option", () => {
  const start_ = (account: NonNullable<MockOptions["account"]>) => {
    server.use(...createHandlers(demoApi, { account }));
  };

  it("does not let a PIN-locked user in, even with the right PIN", async () => {
    start_({ user: MOCK_EMAILS.phLocked, gate: "pin_locked" });
    await adoptSession();
    const answer = await unlock(MOCK_PIN);
    expect([answer.status, answer.body.code]).toEqual([423, "pin_locked"]);
  });

  it("derives the gate from the user when none is given", async () => {
    for (const [email, gate] of [
      [MOCK_EMAILS.phLocked, "pin_locked"],
      [MOCK_EMAILS.phInvited, "set_pin"],
      [MOCK_EMAILS.phStaff, "enter_pin"],
    ] as const) {
      start_({ user: email });
      expect((await adoptSession()).gate).toBe(gate);
    }
  });

  it("keeps an explicit open gate for an active user with a PIN", async () => {
    start_({ user: MOCK_EMAILS.phStaff, gate: "open" });
    expect((await adoptSession()).gate).toBe("open");
  });

  it("is found by id as well as by email, in any case", async () => {
    start_({ user: MOCK_EMAILS.phStaff.toUpperCase(), gate: "open" });
    const session = await adoptSession();
    start_({ user: session.user_id, gate: "open" });
    expect((await adoptSession()).user_id).toBe(session.user_id);
  });

  it.each([
    ["an unknown user", { user: "nobody@example.com" }],
    ["a revoked user", { user: MOCK_EMAILS.usRevoked }],
    ["a PIN-locked user at another gate", { user: MOCK_EMAILS.phLocked, gate: "open" as const }],
    [
      "a user with no PIN at enter_pin",
      { user: MOCK_EMAILS.phInvited, gate: "enter_pin" as const },
    ],
    ["a user with no PIN at open", { user: MOCK_EMAILS.phInvited, gate: "open" as const }],
    ["a user with a PIN at set_pin", { user: MOCK_EMAILS.phStaff, gate: "set_pin" as const }],
  ])("refuses %s, naming the option", (_name, account) => {
    expect(() => createHandlers(demoApi, { account })).toThrow(/account/);
  });
});
