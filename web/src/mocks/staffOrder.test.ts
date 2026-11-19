import { describe, expect, it } from "vitest";
import type { components } from "../api/schema";
import { adoptSession, raw } from "../test/mockSession";
import { server } from "../test/setup";
import { demoApi } from "./demo-api";
import { createHandlers } from "./handlers";
import { MOCK_EMAILS, MOCK_PIN } from "./staff";

type User = components["schemas"]["UserOut"];

const WRONG = "999999";
const as = async (email: string) => {
  server.use(...createHandlers(demoApi, { account: { user: email, gate: "open" } }));
  await adoptSession();
};
const idOf = async (email: string) => {
  const rows = (await raw("GET", "/api/v1/users")).body as unknown as User[];
  const found = rows.find((u) => u.email === email);
  if (!found) throw new Error(`no ${email}`);
  return found.id;
};
const act = (path: string, pin = MOCK_PIN) => raw("POST", path, { body: { pin } });
const outcome = (answer: { status: number; body: Record<string, unknown> }) => [
  answer.status,
  answer.body["code"],
];

describe("the order the server checks a staff action in", () => {
  it("answers 404 for an unknown id before it looks at the PIN, and counts no try", async () => {
    await as(MOCK_EMAILS.admin);
    const nobody = "00000000-0000-4000-8000-0000000003ff";
    const staff = await idOf(MOCK_EMAILS.phStaff);
    for (const route of ["revoke", "pin-reset"]) {
      expect(outcome(await act(`/api/v1/users/${nobody}/${route}`, WRONG))).toEqual([
        404,
        "not_found",
      ]);
    }
    expect((await act(`/api/v1/users/${staff}/revoke`, WRONG)).body["tries_left"]).toBe(4);
  });

  it("answers 404 for another facility's person to a head nurse, and counts no try", async () => {
    await as(MOCK_EMAILS.admin);
    const other = await idOf(MOCK_EMAILS.usStaff);
    await as(MOCK_EMAILS.phHead);
    const mine = await idOf(MOCK_EMAILS.phStaff);
    expect(outcome(await act(`/api/v1/users/${other}/pin-reset`, WRONG))).toEqual([
      404,
      "not_found",
    ]);
    expect(outcome(await act(`/api/v1/users/${other}/pin-reset`))).toEqual([404, "not_found"]);
    expect((await act(`/api/v1/users/${mine}/pin-reset`, WRONG)).body["tries_left"]).toBe(4);
  });

  it("answers 403 for yourself before it looks at the PIN, and counts no try", async () => {
    await as(MOCK_EMAILS.admin);
    const self = await idOf(MOCK_EMAILS.admin);
    const staff = await idOf(MOCK_EMAILS.phStaff);
    for (const route of ["revoke", "pin-reset"]) {
      expect(outcome(await act(`/api/v1/users/${self}/${route}`, WRONG))).toEqual([
        403,
        "forbidden",
      ]);
    }
    expect((await act(`/api/v1/users/${staff}/revoke`, WRONG)).body["tries_left"]).toBe(4);
  });

  it("answers 404 to a head nurse about the admin (no facility is not hers), and counts no try", async () => {
    await as(MOCK_EMAILS.admin);
    const admin = await idOf(MOCK_EMAILS.admin);
    await as(MOCK_EMAILS.phHead);
    const staff = await idOf(MOCK_EMAILS.phStaff);
    expect(outcome(await act(`/api/v1/users/${admin}/pin-reset`, WRONG))).toEqual([
      404,
      "not_found",
    ]);
    expect((await act(`/api/v1/users/${staff}/pin-reset`, WRONG)).body["tries_left"]).toBe(4);
  });

  it("checks the PIN only for a target that is there and allowed", async () => {
    await as(MOCK_EMAILS.admin);
    const staff = await idOf(MOCK_EMAILS.phStaff);
    expect((await act(`/api/v1/users/${staff}/revoke`, "12")).status).toBe(422);
    expect(outcome(await act(`/api/v1/users/${staff}/revoke`, WRONG))).toEqual([403, "pin_wrong"]);
  });
});
