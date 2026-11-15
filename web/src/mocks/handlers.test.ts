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

  describe("PUT /api/v1/session/shift", () => {
    const choice = (facility: string, code: string) => {
      const found = demoApi.facilities[facility]?.shift_choices.find((c) => c.code === code);
      if (!found) throw new Error(`no ${code} shift`);
      return found;
    };

    it("answers 401 without a session", async () => {
      server.use(...createHandlers());
      const { response, error } = await api.PUT("/api/v1/session/shift", {
        body: { starts_at: choice("ph-demo", "2-10").starts_at },
      });
      expect(response.status).toBe(401);
      expect(error?.code).toBe("not_signed_in");
    });

    it("answers 403 forbidden for the admin", async () => {
      server.use(...createHandlers());
      await signIn("admin", null);
      const { response, error } = await api.PUT("/api/v1/session/shift", {
        body: { starts_at: choice("ph-demo", "2-10").starts_at },
      });
      expect(response.status).toBe(403);
      expect(error?.code).toBe("forbidden");
    });

    it("answers 422 invalid_request when starts_at is not one of the facility's shifts", async () => {
      server.use(...createHandlers());
      await signIn("staff_nurse", "ph-demo");
      const { response, error } = await api.PUT("/api/v1/session/shift", {
        body: { starts_at: "2026-11-11T15:00:00Z" },
      });
      expect(response.status).toBe(422);
      expect(error?.code).toBe("invalid_request");
      expect(error?.errors?.[0]?.field).toBe("body.starts_at");
    });

    it("returns the session with the new shift, comparing instants", async () => {
      server.use(...createHandlers());
      await signIn("staff_nurse", "ph-demo");
      const target = choice("ph-demo", "2-10");
      // Same instant, written with an offset instead of Z.
      const offset = new Date(target.starts_at).toISOString().replace("Z", "+00:00");
      const { response, data } = await api.PUT("/api/v1/session/shift", {
        body: { starts_at: offset },
      });
      expect(response.status).toBe(200);
      expect(data?.shift?.code).toBe("2-10");
      expect((await api.GET("/api/v1/session")).data?.shift?.code).toBe("2-10");
    });
  });
});

describe("rough-note writes", () => {
  const post = (patientId: string, key: string, text: string) =>
    api.POST("/api/v1/patients/{patient_id}/rough-notes", {
      params: { path: { patient_id: patientId }, header: { "Idempotency-Key": key } },
      body: { text },
    });
  const notesOf = async (patientId: string) =>
    (
      await api.GET("/api/v1/patients/{patient_id}", {
        params: { path: { patient_id: patientId } },
      })
    ).data?.notes ?? [];

  it("adds one note to the patient and replays the same job for the same key and text", async () => {
    server.use(...createHandlers());
    await signIn("staff_nurse", "ph-demo");
    const patient = firstPatient("ph-demo");
    const first = await post(patient.id, "k-a", "pt c/o hilo");
    const again = await post(patient.id, "k-a", "pt c/o hilo");
    expect(again.response.status).toBe(202);
    expect(again.data?.id).toBe(first.data?.id);
    const notes = await notesOf(patient.id);
    expect(notes).toHaveLength(1);
    expect(notes[0]?.job.status).toBe("queued");
    expect(notes[0]?.note_status).toBeNull();
  });

  it("answers 422 idempotency_key_reused for the same key with other text", async () => {
    server.use(...createHandlers());
    await signIn("staff_nurse", "ph-demo");
    const patient = firstPatient("ph-demo");
    await post(patient.id, "k-b", "pt c/o hilo");
    const other = await post(patient.id, "k-b", "pt c/o hilo since 2am");
    expect(other.response.status).toBe(422);
    expect(other.error?.code).toBe("idempotency_key_reused");
    expect(await notesOf(patient.id)).toHaveLength(1);
  });

  it("answers 422 invalid_request for an empty or too long note", async () => {
    server.use(...createHandlers());
    await signIn("staff_nurse", "ph-demo");
    const patient = firstPatient("ph-demo");
    expect((await post(patient.id, "k-c", "   ")).error?.code).toBe("invalid_request");
    expect((await post(patient.id, "k-d", "a".repeat(4001))).response.status).toBe(422);
    expect((await post(patient.id, "k-e", "a".repeat(4000))).response.status).toBe(202);
  });

  it("shows the note as a ready draft once the job has answered succeeded", async () => {
    server.use(...createHandlers());
    await signIn("staff_nurse", "ph-demo");
    const patient = firstPatient("ph-demo");
    const jobId = (await post(patient.id, "k-f", "pt c/o hilo")).data?.id ?? "";
    const poll = () =>
      api.GET("/api/v1/draft-jobs/{job_id}", { params: { path: { job_id: jobId } } });
    await poll();
    await poll();
    const [note] = await notesOf(patient.id);
    expect(note?.job.status).toBe("succeeded");
    expect(note?.note_status).toBe("draft");
  });

  it("starts every createHandlers() call from clean demo data", async () => {
    server.use(...createHandlers());
    await signIn("staff_nurse", "ph-demo");
    await post(firstPatient("ph-demo").id, "k-g", "pt c/o hilo");
    server.resetHandlers();
    server.use(...createHandlers());
    await signIn("staff_nurse", "ph-demo");
    expect(await notesOf(firstPatient("ph-demo").id)).toEqual([]);
  });
});

describe("patient detail follows the chosen shift", () => {
  it("shows the shift picked in the header", async () => {
    server.use(...createHandlers());
    await signIn("staff_nurse", "ph-demo");
    const patient = firstPatient("ph-demo");
    const target = demoApi.facilities["ph-demo"]?.shift_choices.find((c) => c.code === "2-10");
    await api.PUT("/api/v1/session/shift", { body: { starts_at: target?.starts_at ?? "" } });
    const { data } = await api.GET("/api/v1/patients/{patient_id}", {
      params: { path: { patient_id: patient.id } },
    });
    expect(data?.shift.code).toBe("2-10");
  });
});
