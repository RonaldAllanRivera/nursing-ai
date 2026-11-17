import { http, HttpResponse, type HttpHandler } from "msw";
import type { components } from "../api/schema";
import { demoApi } from "./demo-api";
import { createDrafts, dressed, draftAgainRoute, queuedView } from "./draftJobs";
import type { MockOptions } from "./options";
import { problem } from "./problems";
import { createSession } from "./session";
import { facilityRoutes } from "./facilityRoutes";
import { sessionRoutes } from "./sessionRoutes";
import { createStaff } from "./staff";
import { staffRoutes } from "./staffRoutes";
import type { DemoApi } from "./types";

type Schemas = components["schemas"];
type Line = Schemas["DraftLine"];

// The mock keeps its own copies of the server's rules, so the web's code can't agree with itself.

/** Every line, in the order of the draft: each entry's focus, then its D, A and R lines. */
function linesInOrder(draft: Schemas["FdarDraft"]): Line[] {
  return draft.entries.flatMap((e) => [e.focus, ...e.data, ...e.action, ...e.response]);
}

/** Core's rule: a line needs review while it is pending and its source was not found. */
function needsReview(line: Line): boolean {
  return line.review === "pending" && line.status !== "source_found";
}

/** The mock's stand-in for the server's SHA-256 of the signed text. */
const FIXED_HASH = "9f2c7a41d83be5106a7c4de2f0b19853c6e7a2d4b8f01c93e5a6d7084b2c1f3e";

/**
 * The P1 endpoints answered from the demo cases, with the state a session needs (who is signed
 * in, how often a job was polled). The web lane adds the write behaviours.
 */
export function createHandlers(
  source: DemoApi = demoApi,
  options: MockOptions = {},
): HttpHandler[] {
  // Writes change this copy, so every call (every test, every page load) starts clean.
  const data = structuredClone(source);
  const staff = createStaff();
  const state = createSession(data, options, staff);
  const drafts = createDrafts(data, source, options);
  const { guard, session } = state;
  const polls = new Map<string, number>();
  const sent = new Map<string, { text: string; jobId: string }>();

  /**
   * The checks every write to a note makes, in the API's order: signed in (401), the CSRF token
   * (403), the gate (423), a nurse (403), If-Match sent (428), the note (404), then locked (409)
   * before stale (412), so a note signed somewhere else answers "locked" whatever version the
   * screen holds.
   */
  function writeGate(
    noteId: string,
    request: Request,
  ):
    | { refusal: Response; note?: never; user?: never }
    | { refusal?: never; note: Schemas["NoteOut"]; user: string } {
    const gated = guard(request);
    if (gated.refusal) return { refusal: gated.refusal };
    const current = gated.session;
    if (current.facility_key === null) return { refusal: problem(403, "forbidden") };
    const ifMatch = request.headers.get("If-Match");
    if (!ifMatch) return { refusal: problem(428, "precondition_required") };
    const note = data.notes[noteId];
    if (!note) return { refusal: problem(404, "not_found") };
    if (note.status !== "draft") return { refusal: problem(409, "note_locked") };
    if (ifMatch !== `"v${String(note.version)}"`) return { refusal: problem(412, "stale_version") };
    return { note, user: current.user_id };
  }

  /** The demo's own copy of a line: what "put back" returns it to. */
  function original(noteId: string, lineId: string) {
    const note = source.notes[noteId];
    return note ? linesInOrder(note.draft).find((l) => l.id === lineId) : undefined;
  }

  /** The patient page's list for the shift shows the note as signed or discarded. */
  function setShiftNoteStatus(note: Schemas["NoteOut"], status: "signed" | "discarded") {
    for (const detail of Object.values(data.patientDetails)) {
      for (const entry of detail.notes) {
        // A rough note drafted again names its draft by the job, not by the demo's rough note.
        if (entry.rough_note_id === note.rough_note_id || entry.job.note_id === note.id) {
          entry.note_status = status;
        }
      }
    }
  }

  /** A write went through: one version on, and the new ETag with the note. */
  function saved(note: Schemas["NoteOut"]) {
    note.version += 1;
    return HttpResponse.json(note, { headers: { ETag: `"v${String(note.version)}"` } });
  }

  return [
    http.get("*/api/v1/health", () => HttpResponse.json({ status: "healthy", database: "ok" })),

    http.get("*/api/v1/personas", () => HttpResponse.json(data.personas)),

    ...sessionRoutes(state, options),
    ...staffRoutes(state, data, staff),
    draftAgainRoute(state, data, drafts),

    http.post("*/api/v1/session", async ({ request }) => {
      const body = (await request.json()) as Schemas["SessionIn"];
      const found = data.sessions[body.persona_id];
      if (!found) return problem(404, "not_found");
      return HttpResponse.json(state.startPersona(body.persona_id), { status: 201 });
    }),

    http.get("*/api/v1/session", () => {
      const current = session();
      // The web's activity heartbeat: reading an open session keeps it open.
      if (current?.gate === "open") state.touch();
      return current ? HttpResponse.json(current) : problem(401, "not_signed_in");
    }),

    http.put("*/api/v1/session/shift", async ({ request }) => {
      const gated = guard(request);
      if (gated.refusal) return gated.refusal;
      const current = gated.session;
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
      state.setShift(choice);
      return HttpResponse.json({ ...current, shift: choice });
    }),

    http.delete("*/api/v1/session", ({ request }) => {
      if (session()) {
        const checked = state.guardSession(request);
        if (checked.refusal) return checked.refusal;
      }
      state.end();
      return new HttpResponse(null, { status: 204 });
    }),

    ...facilityRoutes(state, data, source, options),

    http.get("*/api/v1/patients", ({ request }) => {
      const gated = guard(request);
      if (gated.refusal) return gated.refusal;
      const current = gated.session;
      if (current.facility_key === null) return problem(403, "forbidden");
      const key = current.facility_key as keyof DemoApi["patients"];
      return HttpResponse.json(data.patients[key]);
    }),

    http.get<{ id: string }>("*/api/v1/patients/:id", ({ params, request }) => {
      const gated = guard(request);
      if (gated.refusal) return gated.refusal;
      const current = gated.session;
      if (current.facility_key === null) return problem(403, "forbidden");
      const found = data.patientDetails[params.id];
      if (!found) return problem(404, "not_found");
      // The page shows the shift the nurse picked in the header.
      return HttpResponse.json(state.shift() ? { ...found, shift: state.shift() } : found);
    }),

    http.post<{ id: string }>("*/api/v1/patients/:id/rough-notes", async ({ params, request }) => {
      const gated = guard(request);
      if (gated.refusal) return gated.refusal;
      const current = gated.session;
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
      let job = jobId === undefined ? undefined : data.jobs[jobId];
      if (!job) return problem(404, "not_found");
      if (!earlier) {
        // The `failDraft` option swaps this one save's job for a failed one.
        job = drafts.jobFor(job);
        drafts.authors.set(job.rough_note_id, current.user_id);
        sent.set(key, { text: body.text, jobId: job.id });
      }
      const queued = queuedView(job);
      if (!earlier) {
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

    http.get<{ id: string }>("*/api/v1/draft-jobs/:id", ({ params, request }) => {
      // The poll runs with nobody at the screen, so it doesn't count as activity.
      const gated = guard(request, false);
      if (gated.refusal) return gated.refusal;
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
      return HttpResponse.json(seen === 1 ? queuedView(job) : dressed(job));
    }),

    http.get<{ id: string }>("*/api/v1/notes/:id", ({ params, request }) => {
      const gated = guard(request);
      if (gated.refusal) return gated.refusal;
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
            if (line.review === "removed") {
              return problem(422, "invalid_request", [
                { field: "body.action", message: "Put the line back before you confirm it." },
              ]);
            }
            // An edited or confirmed line stays as it is: "edited" is the only record of a
            // rewrite. Nothing changed, so there is no new version (the API answers the same).
            if (line.review !== "pending") {
              return HttpResponse.json(note, {
                headers: { ETag: `"v${String(note.version)}"` },
              });
            }
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
            // Checked again, only for a line that had differing numbers: one is fixed when its
            // words no longer occur in the new text; the others stay, at their new places.
            if (line.number_mismatches.length > 0) {
              const text = line.text;
              line.number_mismatches = line.number_mismatches.flatMap((m) => {
                const at = text.indexOf(m.draft_text);
                if (at < 0) return [];
                const start = Array.from(text.slice(0, at)).length;
                const end = start + Array.from(m.draft_text).length;
                return [{ ...m, draft_span: { start, end } }];
              });
              if (line.number_mismatches.length === 0) line.status = "source_found";
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

    http.post<{ id: string }>("*/api/v1/notes/:id/sign", async ({ params, request }) => {
      const gate = writeGate(params.id, request);
      if (gate.refusal) return gate.refusal;
      const { note, user } = gate;
      const wrongPin = state.checkPin(((await request.json()) as Schemas["SignNoteIn"]).pin);
      if (wrongPin) return wrongPin;
      const open = linesInOrder(note.draft).filter(needsReview);
      if (open.length > 0) {
        return problem(
          409,
          "review_incomplete",
          undefined,
          open.map((l) => l.id),
        );
      }
      note.status = "signed";
      note.signature = {
        signed_by: user,
        signed_at: new Date().toISOString(),
        content_hash: FIXED_HASH,
      };
      setShiftNoteStatus(note, "signed");
      return saved(note);
    }),

    http.post<{ id: string }>("*/api/v1/notes/:id/discard", ({ params, request }) => {
      const gate = writeGate(params.id, request);
      if (gate.refusal) return gate.refusal;
      const { note, user } = gate;
      note.status = "discarded";
      note.discard = { discarded_at: new Date().toISOString(), discarded_by: user };
      setShiftNoteStatus(note, "discarded");
      return saved(note);
    }),
  ];
}
