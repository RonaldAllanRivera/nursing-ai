import { http, HttpResponse, type HttpHandler } from "msw";
import type { components } from "../api/schema";
import type { MockOptions } from "./options";
import { problem } from "./problems";
import type { MockSession } from "./session";
import type { DemoApi } from "./types";

type Schemas = components["schemas"];
type Job = Schemas["DraftJobOut"];

/** The server's rule: only these failures are worth another try. */
export function isRetryable(job: Pick<Job, "status" | "failure">): boolean {
  return (
    job.status === "failed" &&
    (job.failure === "provider_error" || job.failure === "invalid_output")
  );
}

/** A job as the API answers it, with `retryable` worked out from its failure. */
export function dressed(job: Job): Job {
  return { ...job, retryable: isRetryable(job) };
}

/** The job as the first poll finds it: queued, with nothing to show yet. */
export function queuedView(job: Job): Job {
  return { ...job, status: "queued", failure: null, note_id: null, retryable: false };
}

/**
 * The draft jobs the mock makes beyond the demo's own: a failed one (the `failDraft` option) and
 * the new one "Try drafting again" starts. The frozen demo data has one job per patient, so a new
 * job copies the finished job of the same patient.
 */
export function createDrafts(data: DemoApi, source: DemoApi, options: MockOptions) {
  let made = 0;
  let failNext = options.failDraft;
  /** Who saved each rough note: only they can try again. */
  const authors = new Map<string, string>();

  const newId = () => {
    made += 1;
    return `00000000-0000-4000-8000-0000000007${String(made).padStart(2, "0")}`;
  };
  const store = (job: Job) => {
    data.jobs[job.id] = job;
    return job;
  };

  return {
    authors,
    /** The job a rough note saved for this patient drafts through (a failed one, once, if asked). */
    jobFor(base: Job): Job {
      if (failNext === undefined) return base;
      const failure = failNext;
      failNext = undefined;
      return store(dressed({ ...base, id: newId(), status: "failed", failure, note_id: null }));
    },
    /** A new job for the patient's rough note, which then drafts like any job. */
    retryFor(patientId: string, base: Job): Job {
      const finished = source.jobs[data.jobForPatient[patientId] ?? ""] ?? base;
      return store({ ...finished, id: newId(), rough_note_id: base.rough_note_id });
    },
  };
}

export type Drafts = ReturnType<typeof createDrafts>;

/** "Try drafting again": the open job if there is one, else a new job after a retryable failure. */
export function draftAgainRoute(state: MockSession, data: DemoApi, drafts: Drafts): HttpHandler {
  return http.post<{ id: string }>("*/api/v1/rough-notes/:id/draft-jobs", ({ params, request }) => {
    const gate = state.guard(request);
    if (gate.refusal) return gate.refusal;
    const { session } = gate;
    if (session.facility_key === null) return problem(403, "forbidden");
    // The newest row for a rough note shows its newest job.
    const rows = Object.entries(data.patientDetails).flatMap(([patientId, detail]) =>
      detail.notes
        .filter((n) => n.rough_note_id === params.id)
        .map((entry) => ({ patientId, entry })),
    );
    const newest = rows.at(-1);
    if (!newest) return problem(404, "not_found");
    if (drafts.authors.get(params.id) !== session.user_id) return problem(403, "forbidden");
    const { entry, patientId } = newest;
    const open = (job: Job) =>
      HttpResponse.json(job, {
        status: 202,
        headers: { Location: `/api/v1/draft-jobs/${job.id}` },
      });
    if (entry.job.status === "queued" || entry.job.status === "running") return open(entry.job);
    if (entry.job.status === "succeeded") return problem(409, "already_drafted");
    if (!isRetryable(entry.job)) return problem(409, "not_retryable");
    const fresh = drafts.retryFor(patientId, entry.job);
    entry.job = queuedView(fresh);
    entry.note_status = null;
    return open(entry.job);
  });
}
