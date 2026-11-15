import { describe, expect, it } from "vitest";
import { api } from "../api/client";
import type { components } from "../api/schema";
import { server } from "../test/setup";
import { demoApi } from "./demo-api";
import { createHandlers } from "./handlers";

type Settings = components["schemas"]["FacilitySettings"];
type Shift = components["schemas"]["ShiftDefinition"];

async function signIn(role: string, facility: string | null) {
  const found = demoApi.personas.find((p) => p.role === role && p.facility_key === facility);
  if (!found) throw new Error(`no ${role} persona`);
  return api.POST("/api/v1/session", { body: { persona_id: found.id } });
}

/** The saved settings of a facility, as the form would send them. */
function settingsOf(key: string): Settings {
  const profile = demoApi.facilities[key]?.profile;
  if (!profile) throw new Error(`no ${key}`);
  const { key: kept, ...rest } = structuredClone(profile);
  expect(kept).toBe(key);
  return rest;
}

/** Changes one shift of a copy of the settings. */
function withShift(body: Settings, at: number, change: Partial<Shift>): Settings {
  const shifts = body.shifts.map((s, i) => (i === at ? { ...s, ...change } : s));
  return { ...body, shifts };
}

const put = (key: string, body: Settings, ifMatch: string | null = '"f1"') =>
  api.PUT("/api/v1/facilities/{facility_key}", {
    params: { path: { facility_key: key }, header: { "If-Match": ifMatch } },
    body,
  });

describe("PUT /api/v1/facilities/{facility_key}", () => {
  it("answers 401 without a session", async () => {
    server.use(...createHandlers());
    const { response, error } = await put("ph-demo", settingsOf("ph-demo"));
    expect(response.status).toBe(401);
    expect(error?.code).toBe("not_signed_in");
  });

  it("answers 403 for a nurse", async () => {
    server.use(...createHandlers());
    await signIn("staff_nurse", "ph-demo");
    const { response, error } = await put("ph-demo", settingsOf("ph-demo"));
    expect(response.status).toBe(403);
    expect(error?.code).toBe("forbidden");
  });

  it("answers 404 for a facility that does not exist", async () => {
    server.use(...createHandlers());
    await signIn("admin", null);
    expect((await put("nowhere", settingsOf("ph-demo"))).response.status).toBe(404);
  });

  it("answers 428 without If-Match", async () => {
    server.use(...createHandlers());
    await signIn("admin", null);
    const { response, error } = await put("ph-demo", settingsOf("ph-demo"), null);
    expect(response.status).toBe(428);
    expect(error?.code).toBe("precondition_required");
  });

  it("answers 412 for a stale version", async () => {
    server.use(...createHandlers());
    await signIn("admin", null);
    const { response, error } = await put("ph-demo", settingsOf("ph-demo"), '"f9"');
    expect(response.status).toBe(412);
    expect(error?.code).toBe("stale_version");
  });

  it("answers 422 with a body error when the shifts leave a gap", async () => {
    server.use(...createHandlers());
    await signIn("admin", null);
    const body = withShift(settingsOf("ph-demo"), 1, { starts_local: "15:00:00" });
    const { response, error } = await put("ph-demo", body);
    expect(response.status).toBe(422);
    expect(error?.errors?.map((e) => e.field)).toEqual(["body"]);
  });

  it("answers 422 with the field of a label that is too long", async () => {
    server.use(...createHandlers());
    await signIn("admin", null);
    const body = withShift(settingsOf("ph-demo"), 1, { label: "x".repeat(41) });
    const { response, error } = await put("ph-demo", body);
    expect(response.status).toBe(422);
    expect(error?.errors?.map((e) => e.field)).toEqual(["body.shifts.1.label"]);
  });

  it("answers 422 for an unknown zone, and only then for the rules that need the whole table", async () => {
    server.use(...createHandlers());
    await signIn("admin", null);
    const body = {
      ...withShift(settingsOf("ph-demo"), 1, { code: "6-2" }),
      day_starts_at: "07:00:00",
      timezone: "Mars/Olympus",
    };
    // Like the server: a field's own error comes first, the whole-table rules wait for it.
    const first = await put("ph-demo", body);
    expect(first.error?.errors?.map((e) => e.field)).toEqual(["body.timezone"]);
    const second = await put("ph-demo", { ...body, timezone: "Europe/Paris" });
    expect(second.response.status).toBe(422);
    expect(second.error?.errors?.map((e) => e.field)).toEqual(["body"]);
  });

  it("saves, moves the version on and sends the new ETag", async () => {
    server.use(...createHandlers());
    await signIn("admin", null);
    const body = { ...settingsOf("ph-demo"), name: "SYNTHETIC Renamed Hospital" };
    const saved = await put("ph-demo", body);
    expect(saved.response.status).toBe(200);
    expect(saved.response.headers.get("ETag")).toBe('"f2"');
    expect(saved.data?.version).toBe(2);
    const again = await api.GET("/api/v1/facilities/{facility_key}", {
      params: { path: { facility_key: "ph-demo" } },
    });
    expect(again.data?.profile.name).toBe("SYNTHETIC Renamed Hospital");
    expect(again.data?.profile.key).toBe("ph-demo");
    // The old tag is stale now.
    expect((await put("ph-demo", body)).response.status).toBe(412);
  });

  it("shows a renamed label to a nurse who signs in afterwards", async () => {
    server.use(...createHandlers());
    await signIn("admin", null);
    const body = withShift(settingsOf("ph-demo"), 2, { label: "Night" });
    expect((await put("ph-demo", body)).response.status).toBe(200);
    await api.DELETE("/api/v1/session");
    const nurse = await signIn("staff_nurse", "ph-demo");
    expect(nurse.data?.shift?.code).toBe("10-6");
    expect(nurse.data?.shift?.label).toBe("Night");
    const facility = await api.GET("/api/v1/facilities/{facility_key}", {
      params: { path: { facility_key: "ph-demo" } },
    });
    expect(facility.data?.shift_choices.find((c) => c.code === "10-6")?.label).toBe("Night");
  });
});
