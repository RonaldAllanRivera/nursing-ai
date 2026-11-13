import { describe, expect, it } from "vitest";
import { api } from "../api/client";
import { server } from "../test/setup";
import { demoApi } from "./demo-api";
import { createHandlers } from "./handlers";

function persona(role: string, facility: string | null) {
  const found = demoApi.personas.find((p) => p.role === role && p.facility_key === facility);
  if (!found) throw new Error(`no ${role} persona`);
  return found;
}

function firstPatient(facility: "ph-demo" | "us-demo") {
  const found = demoApi.patients[facility][0];
  if (!found) throw new Error(`no ${facility} patient`);
  return found;
}

async function signIn(role: string, facility: string | null) {
  await api.POST("/api/v1/session", { body: { persona_id: persona(role, facility).id } });
}

describe("demo API mocks", () => {
  it("serves the demo note with its ETag", async () => {
    server.use(...createHandlers());
    await signIn("staff_nurse", "ph-demo");
    const noteId = Object.keys(demoApi.notes)[0] ?? "";
    const { data, response } = await api.GET("/api/v1/notes/{note_id}", {
      params: { path: { note_id: noteId } },
    });
    expect(response.status).toBe(200);
    expect(response.headers.get("ETag")).toBe('"v1"');
    expect(data?.id).toBe(noteId);
  });

  it("answers a rough note with 202 and then a succeeded job", async () => {
    server.use(...createHandlers());
    await signIn("staff_nurse", "ph-demo");
    const patient = firstPatient("ph-demo");
    const posted = await api.POST("/api/v1/patients/{patient_id}/rough-notes", {
      params: { path: { patient_id: patient.id }, header: { "Idempotency-Key": "k-1" } },
      body: { text: "pt c/o hilo since 2am" },
    });
    expect(posted.response.status).toBe(202);
    expect(posted.data?.status).toBe("queued");
    const jobId = posted.data?.id ?? "";
    expect(posted.response.headers.get("Location")).toBe(`/api/v1/draft-jobs/${jobId}`);

    const poll = () =>
      api.GET("/api/v1/draft-jobs/{job_id}", { params: { path: { job_id: jobId } } });
    expect((await poll()).data?.status).toBe("queued");
    const done = await poll();
    expect(done.data?.status).toBe("succeeded");
    expect(done.data?.note_id).toBe(demoApi.jobs[jobId]?.note_id);
  });

  it("returns the first job when the same Idempotency-Key is sent again", async () => {
    server.use(...createHandlers());
    await signIn("staff_nurse", "us-demo");
    const patient = firstPatient("us-demo");
    const send = () =>
      api.POST("/api/v1/patients/{patient_id}/rough-notes", {
        params: { path: { patient_id: patient.id }, header: { "Idempotency-Key": "k-retry" } },
        body: { text: "0830 pt A&Ox4" },
      });
    const first = await send();
    const again = await send();
    expect(again.data?.id).toBe(first.data?.id);
  });

  it("refuses a rough note without an Idempotency-Key with a 428 problem", async () => {
    server.use(...createHandlers());
    await signIn("staff_nurse", "ph-demo");
    const { error, response } = await api.POST("/api/v1/patients/{patient_id}/rough-notes", {
      params: { path: { patient_id: firstPatient("ph-demo").id } },
      body: { text: "pt still weak" },
    });
    expect(response.status).toBe(428);
    expect(response.headers.get("Content-Type")).toBe("application/problem+json");
    expect(error?.code).toBe("precondition_required");
  });

  it("answers 401 before sign-in and 403 when the admin asks for patients", async () => {
    server.use(...createHandlers());
    expect((await api.GET("/api/v1/session")).response.status).toBe(401);
    await signIn("admin", null);
    const patients = await api.GET("/api/v1/patients");
    expect(patients.response.status).toBe(403);
    expect(patients.error?.code).toBe("forbidden");
  });

  it("lists every facility for the admin and only her own for a nurse", async () => {
    server.use(...createHandlers());
    await signIn("admin", null);
    expect((await api.GET("/api/v1/facilities")).data?.map((f) => f.profile.key)).toEqual([
      "ph-demo",
      "us-demo",
    ]);
    await signIn("head_nurse", "us-demo");
    expect((await api.GET("/api/v1/facilities")).data?.map((f) => f.profile.key)).toEqual([
      "us-demo",
    ]);
  });

  it("reports the mock API as healthy", async () => {
    server.use(...createHandlers());
    const { data } = await api.GET("/api/v1/health");
    expect(data).toEqual({ status: "healthy", database: "ok" });
  });
});
