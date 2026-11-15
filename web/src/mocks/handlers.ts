import { http, HttpResponse, type HttpHandler } from "msw";
import type { components } from "../api/schema";
import { demoApi } from "./demo-api";
import { linesInOrder, needsReview, wordsAt } from "../notes/trace";
import type { DemoApi } from "./types";

type Schemas = components["schemas"];
type ProblemCode = Schemas["Problem"]["code"];

/** The mock's stand-in for the server's SHA-256 of the signed text. */
const FIXED_HASH = "9f2c7a41d83be5106a7c4de2f0b19853c6e7a2d4b8f01c93e5a6d7084b2c1f3e";

const TITLES: Record<number, string> = {
  401: "Not signed in",
  403: "Not allowed",
  404: "Not found",
  422: "The request isn't valid",
  409: "The note can't take this change",
  412: "The note changed",
  428: "A required header is missing",
};

function problem(status: number, code: ProblemCode, errors?: Schemas["FieldError"][]) {
  const body: Schemas["Problem"] = {
    type: "about:blank",
    title: TITLES[status] ?? "Error",
    status,
    code,
    ...(errors ? { errors } : {}),
  };
  return HttpResponse.json(body, {
    status,
    headers: { "Content-Type": "application/problem+json" },
  });
}

/**
 * The P1 endpoints answered from the demo cases, with the state a session needs (who is signed
 * in, how often a job was polled). The web lane adds the write behaviours.
 */
export function createHandlers(source: DemoApi = demoApi): HttpHandler[] {
  // Writes change this copy, so every call (every test, every page load) starts clean.
  const data = structuredClone(source);
  let personaId: string | null = null;
  let shiftOverride: Schemas["ShiftRef"] | null = null;
  const polls = new Map<string, number>();
  const sent = new Map<string, { text: string; jobId: string }>();

  const session = () => {
    const found = personaId === null ? undefined : data.sessions[personaId];
    return found && shiftOverride ? { ...found, shift: shiftOverride } : found;
  };

  /** The checks every write to a note makes, in the brief's order. */
  function writeGate(
    noteId: string,
    request: Request,
  ):
    | { refusal: Response; note?: never; user?: never }
    | { refusal?: never; note: Schemas["NoteOut"]; user: string } {
    const current = session();
    if (!current) return { refusal: problem(401, "not_signed_in") };
    if (current.facility_key === null) return { refusal: problem(403, "forbidden") };
    const note = data.notes[noteId];
    if (!note) return { refusal: problem(404, "not_found") };
    const ifMatch = request.headers.get("If-Match");
    if (!ifMatch) return { refusal: problem(428, "precondition_required") };
    if (ifMatch !== `"v${String(note.version)}"`) return { refusal: problem(412, "stale_version") };
    if (note.status !== "draft") return { refusal: problem(409, "note_locked") };
    return { note, user: current.user_id };
  }

  /** The demo's own copy of a line: what "put back" returns it to. */
  function original(noteId: string, lineId: string) {
    const note = source.notes[noteId];
    return note ? linesInOrder(note.draft).find((l) => l.id === lineId) : undefined;
  }

  /** A write went through: one version on, and the new ETag with the note. */
  function saved(note: Schemas["NoteOut"]) {
    note.version += 1;
    return HttpResponse.json(note, { headers: { ETag: `"v${String(note.version)}"` } });
  }

  return [
    http.get("*/api/v1/health", () => HttpResponse.json({ status: "healthy", database: "ok" })),

    http.get("*/api/v1/personas", () => HttpResponse.json(data.personas)),

    http.post("*/api/v1/session", async ({ request }) => {
      const body = (await request.json()) as Schemas["SessionIn"];
      const found = data.sessions[body.persona_id];
      if (!found) return problem(404, "not_found");
      personaId = body.persona_id;
      shiftOverride = null;
      return HttpResponse.json(found, { status: 201 });
    }),

    http.get("*/api/v1/session", () => {
      const current = session();
      return current ? HttpResponse.json(current) : problem(401, "not_signed_in");
    }),

    http.put("*/api/v1/session/shift", async ({ request }) => {
      const current = session();
      if (!current) return problem(401, "not_signed_in");
      if (current.facility_key === null) return problem(403, "forbidden");
      const body = (await request.json()) as Schemas["ShiftChoiceIn"];
      const wanted = Date.parse(body.starts_at);
      const choice = data.facilities[current.facility_key]?.shift_choices.find(
        (c) => Date.parse(c.starts_at) === wanted,
      );
      if (!choice) {
        return problem(422, "invalid_request", [
          { field: "body.starts_at", message: "That is not one of this facility's shifts." },
        ]);
      }
      shiftOverride = choice;
      return HttpResponse.json({ ...current, shift: choice });
    }),

    http.delete("*/api/v1/session", () => {
      personaId = null;
      shiftOverride = null;
      return new HttpResponse(null, { status: 204 });
    }),

    http.get("*/api/v1/facilities", () => {
      const current = session();
      if (!current) return problem(401, "not_signed_in");
      const all = Object.values(data.facilities);
      const key = current.facility_key;
      return HttpResponse.json(key === null ? all : all.filter((f) => f.profile.key === key));
    }),

    http.get<{ key: string }>("*/api/v1/facilities/:key", ({ params }) => {
      const current = session();
      if (!current) return problem(401, "not_signed_in");
      const found = data.facilities[params.key];
      if (!found) return problem(404, "not_found");
      if (current.facility_key !== null && current.facility_key !== params.key) {
        return problem(403, "forbidden");
      }
      return HttpResponse.json(found, { headers: { ETag: `"f${String(found.version)}"` } });
    }),

    http.get("*/api/v1/patients", () => {
      const current = session();
      if (!current) return problem(401, "not_signed_in");
      if (current.facility_key === null) return problem(403, "forbidden");
      const key = current.facility_key as keyof DemoApi["patients"];
      return HttpResponse.json(data.patients[key]);
    }),

    http.get<{ id: string }>("*/api/v1/patients/:id", ({ params }) => {
      const current = session();
      if (!current) return problem(401, "not_signed_in");
      if (current.facility_key === null) return problem(403, "forbidden");
      const found = data.patientDetails[params.id];
      if (!found) return problem(404, "not_found");
      // The page shows the shift the nurse picked in the header.
      return HttpResponse.json(shiftOverride ? { ...found, shift: shiftOverride } : found);
    }),

    http.post<{ id: string }>("*/api/v1/patients/:id/rough-notes", async ({ params, request }) => {
      const current = session();
      if (!current) return problem(401, "not_signed_in");
      if (current.facility_key === null) return problem(403, "forbidden");
      const key = request.headers.get("Idempotency-Key");
      if (!key) return problem(428, "precondition_required");
      const detail = data.patientDetails[params.id];
      if (!detail) return problem(404, "not_found");
      const body = (await request.json()) as Schemas["RoughNoteIn"];
      if (body.text.trim() === "" || Array.from(body.text).length > 4000) {
        return problem(422, "invalid_request", [
          { field: "body.text", message: "A note is 1 to 4000 characters." },
        ]);
      }
      const earlier = sent.get(key);
      if (earlier && earlier.text !== body.text) return problem(422, "idempotency_key_reused");
      // The frozen demo data has one job per patient, so a second save (new key) replays a job
      // that is already finished. The real API makes a new job each time.
      const jobId = earlier?.jobId ?? data.jobForPatient[params.id];
      const job = jobId === undefined ? undefined : data.jobs[jobId];
      if (!job) return problem(404, "not_found");
      const queued: Schemas["DraftJobOut"] = { ...job, status: "queued", note_id: null };
      if (!earlier) {
        sent.set(key, { text: body.text, jobId: job.id });
        detail.notes.push({
          rough_note_id: job.rough_note_id,
          written_at: new Date().toISOString(),
          note_status: null,
          job: queued,
        });
      }
      return HttpResponse.json(queued, {
        status: 202,
        headers: { Location: `/api/v1/draft-jobs/${job.id}` },
      });
    }),

    http.get<{ id: string }>("*/api/v1/draft-jobs/:id", ({ params }) => {
      if (!session()) return problem(401, "not_signed_in");
      const job = data.jobs[params.id];
      if (!job) return problem(404, "not_found");
      const seen = (polls.get(job.id) ?? 0) + 1;
      polls.set(job.id, seen);
      if (seen > 1) {
        // Once it is done, the patient's notes list shows the draft as ready.
        for (const detail of Object.values(data.patientDetails)) {
          for (const note of detail.notes) {
            if (note.job.id !== job.id) continue;
            note.job = job;
            note.note_status = job.status === "succeeded" ? "draft" : null;
          }
        }
      }
      // The first poll still finds the job queued; after that the draft is ready.
      const answer: Schemas["DraftJobOut"] =
        seen === 1 ? { ...job, status: "queued", note_id: null } : job;
      return HttpResponse.json(answer);
    }),

    http.get<{ id: string }>("*/api/v1/notes/:id", ({ params }) => {
      if (!session()) return problem(401, "not_signed_in");
      const note = data.notes[params.id];
      if (!note) return problem(404, "not_found");
      return HttpResponse.json(note, { headers: { ETag: `"v${String(note.version)}"` } });
    }),

    http.patch<{ id: string; lineId: string }>(
      "*/api/v1/notes/:id/lines/:lineId",
      async ({ params, request }) => {
        const gate = writeGate(params.id, request);
        if (gate.refusal) return gate.refusal;
        const { note } = gate;
        const line = linesInOrder(note.draft).find((l) => l.id === params.lineId);
        if (!line) return problem(404, "not_found");
        const body = (await request.json()) as
          | Schemas["ConfirmLine"]
          | Schemas["EditLine"]
          | Schemas["RemoveLine"]
          | Schemas["RestoreLine"];
        switch (body.action) {
          case "confirm":
            line.review = "confirmed";
            break;
          case "remove":
            if (line.section === "focus") {
              return problem(422, "invalid_request", [
                {
                  field: "body.action",
                  message: "A Focus line can't be removed. Edit it instead.",
                },
              ]);
            }
            line.review = "removed";
            break;
          case "edit": {
            const length = Array.from(body.text.trim()).length;
            if (length < 1 || length > 500) {
              return problem(422, "invalid_request", [
                { field: "body.text", message: "A line is 1 to 500 characters." },
              ]);
            }
            line.text = body.text.trim();
            line.review = "edited";
            // Checked again: a line whose differing numbers are gone is found in the note.
            const stillThere = line.number_mismatches.some(
              (m) => wordsAt(line.text, m.draft_span) === m.draft_text,
            );
            if (!stillThere) {
              line.number_mismatches = [];
              line.status = "source_found";
            }
            break;
          }
          case "restore": {
            const first = original(note.id, line.id);
            line.text = line.ai_text;
            line.review = "pending";
            if (first) {
              line.status = first.status;
              line.number_mismatches = structuredClone(first.number_mismatches);
            }
            break;
          }
        }
        return saved(note);
      },
    ),

    http.post<{ id: string }>("*/api/v1/notes/:id/sign", ({ params, request }) => {
      const gate = writeGate(params.id, request);
      if (gate.refusal) return gate.refusal;
      const { note, user } = gate;
      const open = linesInOrder(note.draft).filter(needsReview);
      if (open.length > 0) {
        return HttpResponse.json(
          {
            type: "about:blank",
            title: "Some lines still need review",
            status: 409,
            code: "review_incomplete",
            line_ids: open.map((l) => l.id),
          } satisfies Schemas["Problem"],
          { status: 409, headers: { "Content-Type": "application/problem+json" } },
        );
      }
      note.status = "signed";
      note.signature = {
        signed_by: user,
        signed_at: new Date().toISOString(),
        content_hash: FIXED_HASH,
      };
      return saved(note);
    }),

    http.post<{ id: string }>("*/api/v1/notes/:id/discard", ({ params, request }) => {
      const gate = writeGate(params.id, request);
      if (gate.refusal) return gate.refusal;
      const { note, user } = gate;
      note.status = "discarded";
      note.discard = { discarded_at: new Date().toISOString(), discarded_by: user };
      for (const detail of Object.values(data.patientDetails)) {
        for (const entry of detail.notes) {
          if (entry.rough_note_id === note.rough_note_id) entry.note_status = "discarded";
        }
      }
      return saved(note);
    }),
  ];
}

export const handlers = createHandlers();
