import { describe, expect, it } from "vitest";
import type { components } from "../api/schema";
import { adoptSession, raw, signInAs } from "../test/mockSession";
import { server } from "../test/setup";
import { demoApi } from "./demo-api";
import { createHandlers } from "./handlers";
import type { MockOptions } from "./options";
import { MOCK_EMAILS } from "./staff";

type Job = components["schemas"]["DraftJobOut"];
type Detail = components["schemas"]["PatientDetail"];

const PATIENT = demoApi.patients["ph-demo"][0]?.id ?? "";
let keys = 0;

const begin = async (options?: MockOptions) => {
  server.use(...createHandlers(demoApi, options));
  await signInAs("staff_nurse", "ph-demo");
};
const save = async () => {
  keys += 1;
  const answer = await raw("POST", `/api/v1/patients/${PATIENT}/rough-notes`, {
    body: { text: "pt c/o hilo" },
    headers: { "Idempotency-Key": `k-${String(keys)}` },
  });
  return answer.body as unknown as Job;
};
const poll = async (id: string, times = 2) => {
  let last: Job | undefined;
  for (let i = 0; i < times; i += 1) {
    last = (await raw("GET", `/api/v1/draft-jobs/${id}`)).body as unknown as Job;
  }
  return last as Job;
};
const again = (roughNoteId: string) => raw("POST", `/api/v1/rough-notes/${roughNoteId}/draft-jobs`);
const shown = async () => {
  const detail = (await raw("GET", `/api/v1/patients/${PATIENT}`)).body as unknown as Detail;
  return detail.notes;
};

describe("a draft job's retryable flag", () => {
  it("is true only for a failed job with a failure worth trying again", async () => {
    for (const [failure, retryable] of [
      ["provider_error", true],
      ["invalid_output", true],
      ["model_refused", false],
      ["ai_budget_reached", false],
      ["replay_missing", false],
    ] as const) {
      await begin({ failDraft: failure });
      const job = await save();
      expect((await poll(job.id)).retryable).toBe(retryable);
    }
    await begin();
    const ok = await save();
    expect(ok.retryable).toBe(false);
    expect((await poll(ok.id)).retryable).toBe(false);
  });
});

describe("failDraft", () => {
  it("fails the next rough note's job and drafts the one after normally", async () => {
    await begin({ failDraft: "provider_error" });
    const first = await save();
    const failed = await poll(first.id);
    expect([failed.status, failed.failure, failed.note_id]).toEqual([
      "failed",
      "provider_error",
      null,
    ]);
    const second = await save();
    expect((await poll(second.id)).status).toBe("succeeded");
  });
});

describe("POST /rough-notes/{id}/draft-jobs", () => {
  it("starts a new job after a retryable failure, which then drafts like any job", async () => {
    await begin({ failDraft: "invalid_output" });
    const first = await save();
    await poll(first.id);
    const retry = await again(first.rough_note_id);
    const job = retry.body as unknown as Job;
    expect(retry.status).toBe(202);
    expect(job.id).not.toBe(first.id);
    expect(retry.headers.get("Location")).toBe(`/api/v1/draft-jobs/${job.id}`);
    expect((await shown()).find((n) => n.rough_note_id === first.rough_note_id)?.job.id).toBe(
      job.id,
    );
    expect((await poll(job.id, 1)).status).toBe("queued");
    const done = await poll(job.id, 1);
    expect([done.status, done.retryable]).toEqual(["succeeded", false]);
    const row = (await shown()).find((n) => n.rough_note_id === first.rough_note_id);
    expect([row?.job.id, row?.note_status]).toEqual([job.id, "draft"]);
  });

  it("answers with the same job while one is queued or running", async () => {
    await begin();
    const first = await save();
    const retry = await again(first.rough_note_id);
    expect(retry.status).toBe(202);
    expect(retry.body["id"]).toBe(first.id);
    expect(retry.headers.get("Location")).toBe(`/api/v1/draft-jobs/${first.id}`);
  });

  it("refuses with already_drafted after a success", async () => {
    await begin();
    const first = await save();
    await poll(first.id);
    const answer = await again(first.rough_note_id);
    expect([answer.status, answer.body.code]).toEqual([409, "already_drafted"]);
  });

  it("refuses with not_retryable after a failure that would fail again", async () => {
    await begin({ failDraft: "model_refused" });
    const first = await save();
    await poll(first.id);
    const answer = await again(first.rough_note_id);
    expect([answer.status, answer.body.code]).toEqual([409, "not_retryable"]);
  });

  it("is for the rough note's author, and 404 for an unknown one", async () => {
    await begin({ failDraft: "provider_error" });
    const first = await save();
    await poll(first.id);
    expect((await again("00000000-0000-4000-8000-0000000000aa")).status).toBe(404);
    server.use(
      ...createHandlers(demoApi, {
        account: { user: MOCK_EMAILS.phStaff, gate: "open" },
        failDraft: "provider_error",
      }),
    );
    await adoptSession();
    const mine = await save();
    await poll(mine.id);
    await signInAs("head_nurse", "ph-demo");
    expect((await again(mine.rough_note_id)).status).toBe(403);
  });

  it("retries the failed row even after a later save for the same patient succeeded", async () => {
    await begin({ failDraft: "provider_error" });
    const failed = await save();
    await poll(failed.id);
    const later = await save();
    await poll(later.id);
    expect(later.rough_note_id).not.toBe(failed.rough_note_id);
    const retry = await again(failed.rough_note_id);
    expect(retry.status).toBe(202);
    expect(retry.body["id"]).not.toBe(failed.id);
    const rows = await shown();
    expect(rows.find((n) => n.rough_note_id === failed.rough_note_id)?.job.id).toBe(
      retry.body["id"],
    );
    expect(rows.find((n) => n.rough_note_id === later.rough_note_id)?.job.id).toBe(later.id);
    expect((await again(later.rough_note_id)).body.code).toBe("already_drafted");
  });
});
