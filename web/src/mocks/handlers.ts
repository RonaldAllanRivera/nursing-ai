import { http, HttpResponse, type HttpHandler } from "msw";
import type { components } from "../api/schema";
import { demoApi } from "./demo-api";
import type { DemoApi } from "./types";

type Schemas = components["schemas"];
type ProblemCode = Schemas["Problem"]["code"];
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

// The server's rules for a facility's settings (core's `FacilitySettings`), copied here and not
// imported from the screen, so a disagreement between the screen and the server shows in a test.

type Settings = Schemas["FacilitySettings"];

/** "HH:MM" or "HH:MM:00" as minutes since midnight, or null (not a whole-minute local time). */
function localMinutes(value: unknown): number | null {
  const found = typeof value === "string" ? /^(\d{2}):(\d{2})(?::00)?$/.exec(value) : null;
  if (!found) return null;
  const hours = Number(found[1]);
  const minutes = Number(found[2]);
  return hours < 24 && minutes < 60 ? hours * 60 + minutes : null;
}

function wholeTime(minutes: number): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(Math.floor(minutes / 60))}:${pad(minutes % 60)}:00`;
}

function isIanaZone(value: unknown): boolean {
  if (typeof value !== "string" || value === "") return false;
  try {
    new Intl.DateTimeFormat("en", { timeZone: value });
    return true;
  } catch {
    return false;
  }
}

function textBetween(value: unknown, max: number): boolean {
  return typeof value === "string" && value.trim().length >= 1 && value.trim().length <= max;
}

/** The field-level checks first; the whole-table checks only when those pass (as pydantic does). */
function settingsErrors(body: Settings): Schemas["FieldError"][] {
  const errors: Schemas["FieldError"][] = [];
  const add = (field: string, message: string) => errors.push({ field, message });
  if (!textBetween(body.name, 120)) add("body.name", "A name is 1 to 120 characters.");
  if (!isIanaZone(body.timezone)) {
    add("body.timezone", "Timezone must be an IANA zone such as Europe/Paris.");
  }
  // The body is untrusted JSON: the types say what it should be, not what it is.
  if (!["en-PH", "en-US"].includes(body.locale)) {
    add("body.locale", "Choose a locale from the list.");
  }
  if (!["24h", "12h"].includes(body.clock)) {
    add("body.clock", "Choose 24-hour or 12-hour.");
  }
  if (localMinutes(body.day_starts_at) === null) {
    add("body.day_starts_at", "A time in whole minutes, like 06:00.");
  }
  if (!Array.isArray(body.shifts) || body.shifts.length < 1) {
    add("body.shifts", "Add at least one shift.");
  } else {
    body.shifts.forEach((shift, i) => {
      if (!textBetween(shift.code, 16))
        add(`body.shifts.${String(i)}.code`, "A code is 1 to 16 characters.");
      if (!textBetween(shift.label, 40))
        add(`body.shifts.${String(i)}.label`, "A label is 1 to 40 characters.");
      if (localMinutes(shift.starts_local) === null) {
        add(`body.shifts.${String(i)}.starts_local`, "A time in whole minutes, like 06:00.");
      }
      if (localMinutes(shift.ends_local) === null) {
        add(`body.shifts.${String(i)}.ends_local`, "A time in whole minutes, like 06:00.");
      }
      if (!["blue", "black", "red"].includes(shift.ink)) {
        add(`body.shifts.${String(i)}.ink`, "Choose blue, black or red.");
      }
      if (
        localMinutes(shift.starts_local) !== null &&
        localMinutes(shift.starts_local) === localMinutes(shift.ends_local)
      ) {
        add(`body.shifts.${String(i)}`, "A shift must end at a different time than it starts.");
      }
    });
  }
  if (errors.length > 0) return errors;

  const whole = (message: string) => [{ field: "body", message }];
  const codes = body.shifts.map((s) => s.code.trim());
  if (new Set(codes).size !== codes.length) return whole("Shift codes must be unique.");
  const shifts = body.shifts
    .map((s) => ({
      start: localMinutes(s.starts_local) ?? 0,
      end: localMinutes(s.ends_local) ?? 0,
    }))
    .sort((a, b) => a.start - b.start);
  for (const [i, current] of shifts.entries()) {
    const following = shifts[(i + 1) % shifts.length];
    if (current.end !== following?.start) {
      return whole("Shifts must cover 24 hours with no gap or overlap.");
    }
  }
  if (!shifts.some((s) => s.start === localMinutes(body.day_starts_at))) {
    return whole("The day must start when one of the shifts starts.");
  }
  return [];
}

const TITLES: Record<number, string> = {
  401: "Not signed in",
  403: "Not allowed",
  404: "Not found",
  422: "The request isn't valid",
  409: "The note can't take this change",
  412: "The note changed",
  428: "A required header is missing",
};

function problem(
  status: number,
  code: ProblemCode,
  errors?: Schemas["FieldError"][],
  lineIds?: string[],
) {
  const body: Schemas["Problem"] = {
    type: "about:blank",
    title: TITLES[status] ?? "Error",
    status,
    code,
    ...(errors ? { errors } : {}),
    ...(lineIds ? { line_ids: lineIds } : {}),
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

  /** A nurse's shift is found by its code in her facility's current shifts: a rename shows at once. */
  const relabelled = (
    facilityKey: string | null,
    shift: Schemas["ShiftRef"],
  ): Schemas["ShiftRef"] => {
    const now = facilityKey === null ? undefined : data.facilities[facilityKey];
    const label = now?.profile.shifts.find((s) => s.code === shift.code)?.label;
    return label === undefined ? shift : { ...shift, label };
  };

  const session = () => {
    const found = personaId === null ? undefined : data.sessions[personaId];
    if (!found) return undefined;
    const shift = shiftOverride ?? found.shift;
    return shift ? { ...found, shift: relabelled(found.facility_key, shift) } : found;
  };

  /**
   * The checks every write to a note makes, in the API's order: signed in (401), a nurse (403),
   * If-Match sent (428), the note (404), then locked (409) before stale (412), so a note signed
   * somewhere else answers "locked" whatever version the screen holds.
   */
  function writeGate(
    noteId: string,
    request: Request,
  ):
    | { refusal: Response; note?: never; user?: never }
    | { refusal?: never; note: Schemas["NoteOut"]; user: string } {
    const current = session();
    if (!current) return { refusal: problem(401, "not_signed_in") };
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
        if (entry.rough_note_id === note.rough_note_id) entry.note_status = status;
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

    http.post("*/api/v1/session", async ({ request }) => {
      const body = (await request.json()) as Schemas["SessionIn"];
      const found = data.sessions[body.persona_id];
      if (!found) return problem(404, "not_found");
      personaId = body.persona_id;
      shiftOverride = null;
      return HttpResponse.json(session(), { status: 201 });
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

    http.put<{ key: string }>("*/api/v1/facilities/:key", async ({ params, request }) => {
      const current = session();
      if (!current) return problem(401, "not_signed_in");
      if (current.facility_key !== null) return problem(403, "forbidden");
      const found = data.facilities[params.key];
      if (!found) return problem(404, "not_found");
      const ifMatch = request.headers.get("If-Match");
      if (!ifMatch) return problem(428, "precondition_required");
      if (ifMatch !== `"f${String(found.version)}"`) return problem(412, "stale_version");
      const body = (await request.json()) as Settings;
      const errors = settingsErrors(body);
      if (errors.length > 0) return problem(422, "invalid_request", errors);
      const shifts = body.shifts.map((s) => ({
        code: s.code.trim(),
        label: s.label.trim(),
        starts_local: wholeTime(localMinutes(s.starts_local) ?? 0),
        ends_local: wholeTime(localMinutes(s.ends_local) ?? 0),
        ink: s.ink,
      }));
      found.profile = {
        ...body,
        key: params.key,
        name: body.name.trim(),
        day_starts_at: wholeTime(localMinutes(body.day_starts_at) ?? 0),
        shifts,
      };
      found.version += 1;
      // The demo's shift choices are fixed dates; a rename shows in them, and a removed code goes.
      found.shift_choices = found.shift_choices.flatMap((choice) => {
        const kept = shifts.find((s) => s.code === choice.code);
        return kept ? [{ ...choice, label: kept.label }] : [];
      });
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

    http.post<{ id: string }>("*/api/v1/notes/:id/sign", ({ params, request }) => {
      const gate = writeGate(params.id, request);
      if (gate.refusal) return gate.refusal;
      const { note, user } = gate;
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
