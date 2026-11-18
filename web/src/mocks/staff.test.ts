import { describe, expect, it } from "vitest";
import type { components } from "../api/schema";
import { adoptSession, raw, signInAs } from "../test/mockSession";
import { server } from "../test/setup";
import { demoApi } from "./demo-api";
import { createHandlers } from "./handlers";
import { MOCK_EMAILS, MOCK_PIN } from "./staff";

type User = components["schemas"]["UserOut"];

const as = async (email: string) => {
  server.use(...createHandlers(demoApi, { account: { user: email, gate: "open" } }));
  await adoptSession();
};
const list = async () => (await raw("GET", "/api/v1/users")).body as unknown as User[];
const byEmail = async (email: string) => {
  const found = (await list()).find((u) => u.email === email);
  if (!found) throw new Error(`no ${email}`);
  return found;
};
const act = (path: string, pin = MOCK_PIN) => raw("POST", path, { body: { pin } });
const invite = (body: object) =>
  raw("POST", "/api/v1/users", { body: { pin: MOCK_PIN, role: "staff_nurse", ...body } });

describe("the staff list", () => {
  it("is refused to every persona and to a staff nurse", async () => {
    server.use(...createHandlers());
    for (const [role, facility] of [
      ["admin", null],
      ["head_nurse", "ph-demo"],
      ["staff_nurse", "ph-demo"],
    ] as const) {
      await signInAs(role, facility);
      expect((await raw("GET", "/api/v1/users")).status).toBe(403);
      const id = "00000000-0000-4000-8000-000000000301";
      expect((await invite({ email: "a@example.com", facility_key: "ph-demo" })).status).toBe(403);
      expect((await act(`/api/v1/users/${id}/revoke`)).status).toBe(403);
      expect((await act(`/api/v1/users/${id}/pin-reset`)).status).toBe(403);
    }
    await as(MOCK_EMAILS.phStaff);
    expect((await raw("GET", "/api/v1/users")).status).toBe(403);
  });

  it("shows the admin every non-persona user, and no persona", async () => {
    await as(MOCK_EMAILS.admin);
    const users = await list();
    expect(users.map((u) => u.email).sort()).toEqual(Object.values(MOCK_EMAILS).sort());
    expect(users.every((u) => u.email.endsWith("@example.com"))).toBe(true);
    const by = (email: string) => users.find((u) => u.email === email);
    expect(by(MOCK_EMAILS.phInvited)?.status).toBe("invited");
    expect(by(MOCK_EMAILS.phLocked)?.pin_locked).toBe(true);
    expect(by(MOCK_EMAILS.usRevoked)?.status).toBe("revoked");
    expect(by(MOCK_EMAILS.admin)?.facility_key).toBeNull();
    expect(JSON.stringify(users)).not.toContain(MOCK_PIN);
  });

  it("shows a head nurse only her facility's staff", async () => {
    await as(MOCK_EMAILS.phHead);
    const users = await list();
    expect(users.length).toBeGreaterThan(1);
    expect(users.every((u) => u.facility_key === "ph-demo")).toBe(true);
  });
});

describe("inviting", () => {
  it("is the admin's alone, lowercases the email and adds an invited row", async () => {
    await as(MOCK_EMAILS.phHead);
    expect((await invite({ email: "x@example.com", facility_key: "ph-demo" })).status).toBe(403);
    await as(MOCK_EMAILS.admin);
    const made = await invite({ email: "New.Nurse@Example.com", facility_key: "us-demo" });
    expect(made.status).toBe(201);
    expect(made.body).toMatchObject({
      email: "new.nurse@example.com",
      display_name: "new.nurse@example.com",
      initials: "N",
      status: "invited",
      pin_locked: false,
      facility_key: "us-demo",
      role: "staff_nurse",
    });
    expect((await list()).some((u) => u.email === "new.nurse@example.com")).toBe(true);
  });

  it("refuses a taken email in any case, and a facility that does not fit the role", async () => {
    await as(MOCK_EMAILS.admin);
    const taken = await invite({
      email: MOCK_EMAILS.usStaff.toUpperCase(),
      facility_key: "us-demo",
    });
    expect([taken.status, taken.body.code]).toEqual([409, "email_taken"]);
    for (const bad of [
      { role: "staff_nurse", facility_key: null },
      { role: "admin", facility_key: "ph-demo" },
      { role: "head_nurse", facility_key: "nowhere" },
    ]) {
      const answer = await invite({ email: "ok@example.com", ...bad });
      expect([answer.status, answer.body.errors?.[0]?.field]).toEqual([422, "body.facility_key"]);
    }
    const admin = await invite({
      email: "second.admin@example.com",
      role: "admin",
      facility_key: null,
    });
    expect(admin.status).toBe(201);
    expect(admin.body).toMatchObject({ role: "admin", facility_key: null });
  });
});

describe("revoking", () => {
  it("keeps the row as revoked, and never the admin themselves", async () => {
    await as(MOCK_EMAILS.admin);
    const target = await byEmail(MOCK_EMAILS.phStaff);
    const done = await act(`/api/v1/users/${target.id}/revoke`);
    expect([done.status, done.body["status"]]).toEqual([200, "revoked"]);
    expect((await byEmail(MOCK_EMAILS.phStaff)).status).toBe("revoked");
    const self = await byEmail(MOCK_EMAILS.admin);
    expect((await act(`/api/v1/users/${self.id}/revoke`)).status).toBe(403);
  });

  it("is the admin's alone, and 404 for an unknown id", async () => {
    await as(MOCK_EMAILS.phHead);
    const target = await byEmail(MOCK_EMAILS.phStaff);
    expect((await act(`/api/v1/users/${target.id}/revoke`)).status).toBe(403);
    await as(MOCK_EMAILS.admin);
    expect((await act("/api/v1/users/00000000-0000-4000-8000-0000000003ff/revoke")).status).toBe(
      404,
    );
  });
});

describe("resetting a PIN", () => {
  it("lets the admin reset anyone but themselves, and clears a locked PIN", async () => {
    await as(MOCK_EMAILS.admin);
    const locked = await byEmail(MOCK_EMAILS.phLocked);
    const done = await act(`/api/v1/users/${locked.id}/pin-reset`);
    expect([done.status, done.body["pin_locked"]]).toEqual([200, false]);
    expect((await byEmail(MOCK_EMAILS.phLocked)).pin_locked).toBe(false);
    const self = await byEmail(MOCK_EMAILS.admin);
    expect((await act(`/api/v1/users/${self.id}/pin-reset`)).status).toBe(403);
  });

  it("lets a head nurse reset staff of her facility, never herself or the admin, and does not see another facility's person", async () => {
    await as(MOCK_EMAILS.admin);
    const ids = {
      us: (await byEmail(MOCK_EMAILS.usStaff)).id,
      admin: (await byEmail(MOCK_EMAILS.admin)).id,
    };
    await as(MOCK_EMAILS.phHead);
    const mine = await byEmail(MOCK_EMAILS.phLocked);
    const self = await byEmail(MOCK_EMAILS.phHead);
    expect((await act(`/api/v1/users/${mine.id}/pin-reset`)).status).toBe(200);
    expect((await act(`/api/v1/users/${self.id}/pin-reset`)).status).toBe(403);
    expect((await act(`/api/v1/users/${ids.us}/pin-reset`)).status).toBe(404);
    expect((await act(`/api/v1/users/${ids.admin}/pin-reset`)).status).toBe(403);
  });
});

describe("every staff action checks the actor's PIN", () => {
  it("refuses a wrong PIN with tries_left, and a malformed one with 422", async () => {
    await as(MOCK_EMAILS.admin);
    const target = await byEmail(MOCK_EMAILS.phStaff);
    const wrong = await act(`/api/v1/users/${target.id}/revoke`, "999999");
    expect([wrong.status, wrong.body.code, wrong.body.tries_left]).toEqual([403, "pin_wrong", 4]);
    const reset = await act(`/api/v1/users/${target.id}/pin-reset`, "999999");
    expect(reset.body.tries_left).toBe(3);
    const made = await invite({ email: "p@example.com", facility_key: "ph-demo", pin: "999999" });
    expect(made.body.code).toBe("pin_wrong");
    expect((await act(`/api/v1/users/${target.id}/revoke`, "12")).status).toBe(422);
    expect((await byEmail(MOCK_EMAILS.phStaff)).status).toBe("active");
  });
});
