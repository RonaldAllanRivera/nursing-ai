import { http, HttpResponse, type HttpHandler } from "msw";
import type { components } from "../api/schema";
import { demoApi } from "./demo-api";
import type { DemoApi } from "./types";

type Schemas = components["schemas"];
type ProblemCode = Schemas["Problem"]["code"];

const TITLES: Record<number, string> = {
  401: "Not signed in",
  403: "Not allowed",
  404: "Not found",
  428: "A required header is missing",
};

function problem(status: number, code: ProblemCode) {
  const body: Schemas["Problem"] = {
    type: "about:blank",
    title: TITLES[status] ?? "Error",
    status,
    code,
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
export function createHandlers(data: DemoApi = demoApi): HttpHandler[] {
  let personaId: string | null = null;
  const polls = new Map<string, number>();
  const jobsByKey = new Map<string, string>();

  const session = () => (personaId === null ? undefined : data.sessions[personaId]);

  return [
    http.get("*/api/v1/health", () => HttpResponse.json({ status: "healthy", database: "ok" })),

    http.get("*/api/v1/personas", () => HttpResponse.json(data.personas)),

    http.post("*/api/v1/session", async ({ request }) => {
      const body = (await request.json()) as Schemas["SessionIn"];
      const found = data.sessions[body.persona_id];
      if (!found) return problem(404, "not_found");
      personaId = body.persona_id;
      return HttpResponse.json(found, { status: 201 });
    }),

    http.get("*/api/v1/session", () => {
      const current = session();
      return current ? HttpResponse.json(current) : problem(401, "not_signed_in");
    }),

    http.delete("*/api/v1/session", () => {
      personaId = null;
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
      return found ? HttpResponse.json(found) : problem(404, "not_found");
    }),

    http.post<{ id: string }>("*/api/v1/patients/:id/rough-notes", ({ params, request }) => {
      const current = session();
      if (!current) return problem(401, "not_signed_in");
      if (current.facility_key === null) return problem(403, "forbidden");
      const key = request.headers.get("Idempotency-Key");
      if (!key) return problem(428, "precondition_required");
      const jobId = jobsByKey.get(key) ?? data.jobForPatient[params.id];
      const job = jobId === undefined ? undefined : data.jobs[jobId];
      if (!job) return problem(404, "not_found");
      jobsByKey.set(key, job.id);
      const queued: Schemas["DraftJobOut"] = { ...job, status: "queued", note_id: null };
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
  ];
}

export const handlers = createHandlers();
