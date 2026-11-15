import { describe, expect, it } from "vitest";
import { api } from "../api/client";
import type { components } from "../api/schema";
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

describe("writes to a note: line actions, sign and discard", () => {
  const NOTE = "00000000-0000-4000-8000-000000000015";
  const NOTE_2 = "00000000-0000-4000-8000-000000000025";
  type Body =
    | components["schemas"]["ConfirmLine"]
    | components["schemas"]["EditLine"]
    | components["schemas"]["RemoveLine"]
    | components["schemas"]["RestoreLine"];

  async function start() {
    server.use(...createHandlers());
    await signIn("staff_nurse", "ph-demo");
  }
  const act = (lineId: string, body: Body, ifMatch: string | null = '"v1"', noteId = NOTE) =>
    api.PATCH("/api/v1/notes/{note_id}/lines/{line_id}", {
      params: {
        path: { note_id: noteId, line_id: lineId },
        header: { "If-Match": ifMatch },
      },
      body,
    });
  const sign = (ifMatch: string | null = '"v1"', noteId = NOTE) =>
    api.POST("/api/v1/notes/{note_id}/sign", {
      params: { path: { note_id: noteId }, header: { "If-Match": ifMatch } },
    });
  const discard = (ifMatch: string | null = '"v1"') =>
    api.POST("/api/v1/notes/{note_id}/discard", {
      params: { path: { note_id: NOTE }, header: { "If-Match": ifMatch } },
    });
  const lineOf = (note: components["schemas"]["NoteOut"] | undefined, id: string) => {
    const found = note?.draft.entries
      .flatMap((e) => [e.focus, ...e.data, ...e.action, ...e.response])
      .find((l) => l.id === id);
    if (!found) throw new Error(`no line ${id}`);
    return found;
  };

  it("refuses a write with no session (401) and the admin (403)", async () => {
    server.use(...createHandlers());
    expect((await act("e1-F", { action: "confirm" })).response.status).toBe(401);
    await signIn("admin", null);
    expect((await act("e1-F", { action: "confirm" })).response.status).toBe(403);
    expect((await sign()).response.status).toBe(403);
    expect((await discard()).response.status).toBe(403);
  });

  it("asks for If-Match (428) and refuses a stale one (412)", async () => {
    await start();
    expect((await act("e1-F", { action: "confirm" }, null)).response.status).toBe(428);
    expect((await act("e1-F", { action: "confirm" }, '"v7"')).response.status).toBe(412);
    expect((await sign(null)).response.status).toBe(428);
    expect((await discard('"v2"')).response.status).toBe(412);
  });

  it("answers an unknown line with 404", async () => {
    await start();
    expect((await act("nope", { action: "confirm" })).response.status).toBe(404);
  });

  it("confirms, removes and restores a line, each answering the new version's ETag", async () => {
    await start();
    const confirmed = await act("e1-F", { action: "confirm" });
    expect(confirmed.response.headers.get("ETag")).toBe('"v2"');
    expect(confirmed.data?.version).toBe(2);
    expect(lineOf(confirmed.data, "e1-F").review).toBe("confirmed");

    const removed = await act("e1-A2", { action: "remove" }, '"v2"');
    expect(lineOf(removed.data, "e1-A2").review).toBe("removed");

    const back = await act("e1-A2", { action: "restore" }, '"v3"');
    const line = lineOf(back.data, "e1-A2");
    expect([line.review, line.status, line.text]).toEqual([
      "pending",
      "no_source",
      "Physician notified.",
    ]);
    expect(back.response.headers.get("ETag")).toBe('"v4"');
  });

  it("refuses to remove a Focus line (422)", async () => {
    await start();
    expect((await act("e1-F", { action: "remove" })).response.status).toBe(422);
  });

  it("edits a line and checks it again: a fixed number clears the mismatch", async () => {
    await start();
    const fixed = await act("e1-D2", { action: "edit", text: "BP 90/60 mmHg, HR 112 bpm." });
    const line = lineOf(fixed.data, "e1-D2");
    expect([line.review, line.status, line.number_mismatches]).toEqual([
      "edited",
      "source_found",
      [],
    ]);
    expect(line.text).toBe("BP 90/60 mmHg, HR 112 bpm.");
    // Restoring puts back the AI's words, its status and its mismatch.
    const back = await act("e1-D2", { action: "restore" }, '"v2"');
    const original = lineOf(back.data, "e1-D2");
    expect([original.review, original.status, original.number_mismatches.length]).toEqual([
      "pending",
      "number_mismatch",
      1,
    ]);
    expect(original.text).toBe(original.ai_text);
  });

  it("keeps the mismatch when an edit leaves the draft's number where it was", async () => {
    await start();
    const kept = await act("e1-D2", { action: "edit", text: "BP 90/60 mmHg, HR 121 bpm, weak." });
    const line = lineOf(kept.data, "e1-D2");
    expect([line.review, line.status]).toEqual(["edited", "number_mismatch"]);
  });

  it("refuses an empty or over-long edit (422)", async () => {
    await start();
    expect((await act("e1-D2", { action: "edit", text: "  " })).response.status).toBe(422);
    expect((await act("e1-D2", { action: "edit", text: "x".repeat(501) })).response.status).toBe(
      422,
    );
  });

  it("refuses to sign while a line needs review, listing them in draft order (409)", async () => {
    await start();
    const refused = await sign();
    expect(refused.response.status).toBe(409);
    expect(refused.error?.code).toBe("review_incomplete");
    expect(refused.error?.line_ids).toEqual(["e1-F", "e1-D2", "e1-A2"]);
  });

  it("signs once every line is dealt with, then locks the note (409 note_locked)", async () => {
    await start();
    await act("e1-F", { action: "confirm" });
    await act("e1-D2", { action: "edit", text: "BP 90/60 mmHg, HR 112 bpm." }, '"v2"');
    await act("e1-A2", { action: "remove" }, '"v3"');
    const signed = await sign('"v4"');
    expect(signed.response.status).toBe(200);
    expect(signed.response.headers.get("ETag")).toBe('"v5"');
    expect(signed.data?.status).toBe("signed");
    expect(signed.data?.signature?.content_hash).toMatch(/^[0-9a-f]{64}$/);
    expect(signed.data?.signature?.signed_by).toBeTruthy();
    const locked = await act("e1-F", { action: "restore" }, '"v5"');
    expect(locked.response.status).toBe(409);
    expect(locked.error?.code).toBe("note_locked");
    expect((await sign('"v5"')).error?.code).toBe("note_locked");
    expect((await discard('"v5"')).error?.code).toBe("note_locked");
  });

  it("discards a draft, and reads as discarded", async () => {
    await start();
    const done = await discard();
    expect(done.data?.status).toBe("discarded");
    expect(done.data?.discard?.discarded_at).toBeTruthy();
    expect(done.response.headers.get("ETag")).toBe('"v2"');
    const read = await api.GET("/api/v1/notes/{note_id}", { params: { path: { note_id: NOTE } } });
    expect(read.data?.status).toBe("discarded");
  });

  it("answers an unknown note with 404, and leaves other notes alone", async () => {
    await start();
    expect((await sign('"v1"', "00000000-0000-4000-8000-0000000000ff")).response.status).toBe(404);
    await discard();
    const other = await api.GET("/api/v1/notes/{note_id}", {
      params: { path: { note_id: NOTE_2 } },
    });
    expect(other.data?.status).toBe("draft");
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
