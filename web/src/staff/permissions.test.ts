import { describe, expect, it } from "vitest";
import {
  canInvite,
  canResetPin,
  canRevoke,
  canSeeStaff,
  sortStaff,
  type StaffActor,
  type StaffTarget,
} from "./permissions";

const ADMIN: StaffActor = { kind: "google", role: "admin", user_id: "a", facility_key: null };
const HEAD: StaffActor = { kind: "google", role: "head_nurse", user_id: "h", facility_key: "ph" };
const STAFF: StaffActor = { kind: "google", role: "staff_nurse", user_id: "s", facility_key: "ph" };
const PERSONA_ADMIN: StaffActor = { ...ADMIN, kind: "persona" };
const PERSONA_HEAD: StaffActor = { ...HEAD, kind: "persona" };

const row = (over: Partial<StaffTarget>): StaffTarget => ({
  id: "t",
  role: "staff_nurse",
  facility_key: "ph",
  status: "active",
  ...over,
});

describe("who sees the Staff screen", () => {
  it("is a Google admin or head nurse, never a staff nurse or a persona", () => {
    expect(canSeeStaff(ADMIN)).toBe(true);
    expect(canSeeStaff(HEAD)).toBe(true);
    expect(canSeeStaff(STAFF)).toBe(false);
    expect(canSeeStaff(PERSONA_ADMIN)).toBe(false);
    expect(canSeeStaff(PERSONA_HEAD)).toBe(false);
  });
});

describe("who can invite", () => {
  it("is a Google admin alone", () => {
    expect(canInvite(ADMIN)).toBe(true);
    expect(canInvite(HEAD)).toBe(false);
    expect(canInvite(STAFF)).toBe(false);
    expect(canInvite(PERSONA_ADMIN)).toBe(false);
  });
});

describe("who can revoke", () => {
  it("lets the admin revoke an invited or active person, never themselves", () => {
    expect(canRevoke(ADMIN, row({ status: "active" }))).toBe(true);
    expect(canRevoke(ADMIN, row({ status: "invited" }))).toBe(true);
    expect(canRevoke(ADMIN, row({ id: "a", role: "admin", facility_key: null }))).toBe(false);
    expect(canRevoke(ADMIN, row({ role: "admin", facility_key: null }))).toBe(true);
    expect(canRevoke(ADMIN, row({ facility_key: "us" }))).toBe(true);
  });

  it("offers nothing on a revoked row", () => {
    expect(canRevoke(ADMIN, row({ status: "revoked" }))).toBe(false);
  });

  it("is not a head nurse's, a staff nurse's or a persona's", () => {
    expect(canRevoke(HEAD, row({}))).toBe(false);
    expect(canRevoke(STAFF, row({}))).toBe(false);
    expect(canRevoke(PERSONA_ADMIN, row({}))).toBe(false);
  });
});

describe("who can reset a PIN", () => {
  it("lets the admin reset anyone with a PIN but themselves, locked or not", () => {
    expect(canResetPin(ADMIN, row({ status: "active" }))).toBe(true);
    expect(canResetPin(ADMIN, row({ role: "head_nurse", facility_key: "us" }))).toBe(true);
    expect(canResetPin(ADMIN, row({ role: "admin", facility_key: null }))).toBe(true);
    expect(canResetPin(ADMIN, row({ id: "a", role: "admin", facility_key: null }))).toBe(false);
  });

  it("offers no reset on an invited row (no PIN yet) or a revoked one", () => {
    expect(canResetPin(ADMIN, row({ status: "invited" }))).toBe(false);
    expect(canResetPin(HEAD, row({ status: "invited" }))).toBe(false);
    expect(canResetPin(ADMIN, row({ status: "revoked" }))).toBe(false);
    expect(canResetPin(HEAD, row({ status: "revoked" }))).toBe(false);
  });

  it("lets a head nurse reset a staff or head nurse of her facility, never herself", () => {
    expect(canResetPin(HEAD, row({}))).toBe(true);
    expect(canResetPin(HEAD, row({ role: "head_nurse" }))).toBe(true);
    expect(canResetPin(HEAD, row({ id: "h", role: "head_nurse" }))).toBe(false);
  });

  it("keeps a head nurse out of another facility and away from the admin", () => {
    expect(canResetPin(HEAD, row({ facility_key: "us" }))).toBe(false);
    expect(canResetPin(HEAD, row({ role: "admin", facility_key: null }))).toBe(false);
  });

  it("is not a staff nurse's or a persona's", () => {
    expect(canResetPin(STAFF, row({}))).toBe(false);
    expect(canResetPin(PERSONA_HEAD, row({}))).toBe(false);
    expect(canResetPin(PERSONA_ADMIN, row({}))).toBe(false);
  });
});

describe("the order of the list", () => {
  const person = (
    name: string,
    status: StaffTarget["status"],
    locked = false,
  ): StaffTarget & { display_name: string; pin_locked: boolean } => ({
    id: name,
    role: "staff_nurse",
    facility_key: "ph",
    status,
    display_name: name,
    pin_locked: locked,
  });

  it("puts a locked PIN first, then active, invited and revoked people, each by name", () => {
    const sorted = sortStaff([
      person("Zed", "revoked"),
      person("Bea", "invited"),
      person("Cal", "active"),
      person("Abe", "active"),
      person("Dot", "active", true),
      person("Eve", "active", true),
    ]);
    expect(sorted.map((p) => p.id)).toEqual(["Dot", "Eve", "Abe", "Cal", "Bea", "Zed"]);
  });

  it("does not change the list it is given", () => {
    const list = [person("B", "active"), person("A", "active")];
    sortStaff(list);
    expect(list.map((p) => p.id)).toEqual(["B", "A"]);
  });
});
