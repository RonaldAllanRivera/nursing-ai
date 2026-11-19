import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { demoApi } from "../mocks/demo-api";
import { server } from "../test/setup";
import {
  AGAIN,
  AGAIN_URL,
  PATIENT_A,
  SLOW,
  form,
  job,
  openPatientA,
  problem,
  rowFor,
  saveAFailedDraft,
  type Schemas,
} from "./draftingKit";

const detail = demoApi.patientDetails[PATIENT_A];
const QUEUED = "00000000-0000-4000-8000-000000000f02";
const queued = (extra: Partial<Schemas["DraftJobOut"]> = {}) =>
  job({ id: QUEUED, status: "queued", failure: null, retryable: false, ...extra });
const list = () => screen.getByRole("list", { name: "Notes this shift" });
const rows = () => within(list()).getAllByRole("listitem");

/** Opens the patient with a shift list of these rows; each read shows the next set (the last stays). */
async function openList(...reads: Schemas["ShiftNoteOut"][][]) {
  let count = 0;
  const app = await openPatientA({}, [
    http.get("*/api/v1/patients/:id", () => {
      count += 1;
      const notes = reads[Math.min(count, reads.length) - 1] ?? [];
      return HttpResponse.json({ ...detail, notes });
    }),
  ]);
  await within(list()).findAllByRole("listitem");
  return { ...app, reads: () => count };
}

describe("the write form follows the newest job", () => {
  it("goes to the new note when she changes the text and saves after a retry that failed again", async () => {
    const second = "00000000-0000-4000-8000-00000000aa01";
    const { router } = await saveAFailedDraft("provider_error");
    const again = await form().findByRole("button", { name: AGAIN }, SLOW);
    server.use(
      http.post(AGAIN_URL, ({ params }) =>
        HttpResponse.json(
          { ...queued({ id: second }), rough_note_id: String(params["id"]) },
          { status: 202 },
        ),
      ),
      http.get("*/api/v1/draft-jobs/:id", ({ params }) => {
        if (params["id"] !== second) return undefined;
        return HttpResponse.json(job({ id: second, rough_note_id: second }));
      }),
    );
    await userEvent.click(again);
    // The retry fails again, so the button is back.
    await form().findByRole("button", { name: AGAIN }, SLOW);
    // She changes the text and saves a new note instead.
    await userEvent.click(screen.getByLabelText("Your note"));
    await userEvent.paste(" more");
    await userEvent.click(screen.getByRole("button", { name: "Save note" }));
    await waitFor(
      () => {
        expect(router.state.location.pathname).toMatch(/^\/notes\//);
      },
      { timeout: 8000 },
    );
  }, 25000);

  it("follows the rough note's newest job, and its draft, when the server says it was already drafted", async () => {
    const done = "00000000-0000-4000-8000-00000000aa02";
    let roughNote = "";
    const { router } = await saveAFailedDraft("provider_error");
    await form().findByRole("button", { name: AGAIN }, SLOW);
    server.use(
      http.post(AGAIN_URL, ({ params }) => {
        roughNote = String(params["id"]);
        return HttpResponse.json(problem(409, "already_drafted"), { status: 409 });
      }),
      http.get("*/api/v1/patients/:id", () =>
        roughNote === ""
          ? undefined
          : HttpResponse.json({
              ...detail,
              notes: [
                rowFor(
                  job({
                    id: done,
                    rough_note_id: roughNote,
                    status: "succeeded",
                    failure: null,
                    retryable: false,
                    note_id: "n-late",
                  }),
                ),
              ],
            }),
      ),
      http.get("*/api/v1/draft-jobs/:id", ({ params }) =>
        params["id"] === done
          ? HttpResponse.json(
              job({
                id: done,
                status: "succeeded",
                failure: null,
                retryable: false,
                note_id: "n-late",
              }),
            )
          : undefined,
      ),
    );
    await userEvent.click(form().getByRole("button", { name: AGAIN }));
    await waitFor(
      () => {
        expect(router.state.location.pathname).toBe("/notes/n-late");
      },
      { timeout: 6000 },
    );
  }, 20000);

  it("moves the focus to the note box when the button it was on goes", async () => {
    await saveAFailedDraft("provider_error");
    const again = await form().findByRole("button", { name: AGAIN }, SLOW);
    server.use(
      http.post(AGAIN_URL, async ({ params }) => {
        await delay(100);
        return HttpResponse.json(
          { ...queued(), rough_note_id: String(params["id"]) },
          { status: 202 },
        );
      }),
      http.get("*/api/v1/draft-jobs/:id", ({ params }) =>
        params["id"] === QUEUED ? HttpResponse.json(queued()) : undefined,
      ),
    );
    await userEvent.click(again);
    await waitFor(() => {
      expect(form().queryByRole("button", { name: AGAIN })).toBeNull();
    });
    expect(screen.getByLabelText("Your note")).toHaveFocus();
  }, 15000);
});

describe("the shift list's Try drafting again", () => {
  const failedRow = rowFor(job());

  it("moves the focus to the row and announces that it is drafting", async () => {
    await openList([failedRow], [rowFor(queued())]);
    server.use(
      http.post(AGAIN_URL, () => HttpResponse.json(queued(), { status: 202 })),
      http.get("*/api/v1/draft-jobs/:id", () => HttpResponse.json(queued())),
    );
    await userEvent.click(within(rows()[0] as HTMLElement).getByRole("button", { name: AGAIN }));
    await waitFor(() => {
      expect(rows()[0]).toHaveTextContent("Drafting");
    });
    expect(within(rows()[0] as HTMLElement).queryByRole("button", { name: AGAIN })).toBeNull();
    expect(rows()[0]).toHaveFocus();
    expect(screen.getByText("Drafting again.")).toBeInTheDocument();
  });

  it("says the daily limit is reached on that row", async () => {
    await openList([failedRow]);
    server.use(
      http.post(AGAIN_URL, () =>
        HttpResponse.json(problem(429, "daily_draft_limit"), { status: 429 }),
      ),
    );
    await userEvent.click(within(rows()[0] as HTMLElement).getByRole("button", { name: AGAIN }));
    expect(
      await within(rows()[0] as HTMLElement).findByText(
        "You've reached today's draft limit. Try again tomorrow.",
      ),
    ).toBeVisible();
  });

  it("clears that row's alert when the list is refreshed", async () => {
    const { queryClient } = await openList([failedRow]);
    server.use(
      http.post(AGAIN_URL, () =>
        HttpResponse.json(problem(429, "daily_draft_limit"), { status: 429 }),
      ),
    );
    await userEvent.click(within(rows()[0] as HTMLElement).getByRole("button", { name: AGAIN }));
    await within(rows()[0] as HTMLElement).findByRole("alert");
    await act(() => queryClient.invalidateQueries({ queryKey: ["patient", PATIENT_A] }));
    await waitFor(() => {
      expect(within(rows()[0] as HTMLElement).queryByRole("alert")).toBeNull();
    });
  });

  it("gives each row its own request: a tap on row B is sent while row A's is out", async () => {
    const other = job({
      id: "00000000-0000-4000-8000-000000000f03",
      rough_note_id: "00000000-0000-4000-8000-000000000e02",
    });
    await openList([failedRow, rowFor(other, "2026-11-11T15:30:00Z")]);
    const sent: string[] = [];
    server.use(
      http.post(AGAIN_URL, async ({ params }) => {
        sent.push(String(params["id"]));
        if (params["id"] === failedRow.rough_note_id) {
          await delay("infinite");
        }
        return HttpResponse.json(queued({ rough_note_id: String(params["id"]) }), { status: 202 });
      }),
    );
    await userEvent.click(within(rows()[0] as HTMLElement).getByRole("button", { name: AGAIN }));
    await userEvent.click(within(rows()[1] as HTMLElement).getByRole("button", { name: AGAIN }));
    await waitFor(() => {
      expect(sent).toEqual([failedRow.rough_note_id, other.rough_note_id]);
    });
  });

  it("asks for the list again only when the new job finishes, not on every render", async () => {
    const done = queued({ status: "succeeded", note_id: "n-ready" });
    const { reads } = await openList([failedRow], [rowFor(queued())], [rowFor(done)]);
    server.use(
      http.post(AGAIN_URL, () => HttpResponse.json(queued(), { status: 202 })),
      http.get("*/api/v1/draft-jobs/:id", () => HttpResponse.json(done)),
    );
    await userEvent.click(within(rows()[0] as HTMLElement).getByRole("button", { name: AGAIN }));
    await within(list()).findByRole("link", { name: "Draft ready" }, SLOW);
    const settled = reads();
    await new Promise((resolve) => setTimeout(resolve, 700));
    expect(reads()).toBe(settled);
    // The list, once at the start, once after the request, once when the job finished.
    expect(settled).toBeLessThanOrEqual(3);
  }, 15000);

  it("keeps following the new job through a poll that fails, until the draft is ready", async () => {
    const done = queued({ status: "succeeded", note_id: "n-ready" });
    await openList([failedRow], [rowFor(queued())], [rowFor(done)]);
    let polls = 0;
    server.use(
      http.post(AGAIN_URL, () => HttpResponse.json(queued(), { status: 202 })),
      http.get("*/api/v1/draft-jobs/:id", () => {
        polls += 1;
        return polls <= 2 ? HttpResponse.json({}, { status: 500 }) : HttpResponse.json(done);
      }),
    );
    await userEvent.click(within(rows()[0] as HTMLElement).getByRole("button", { name: AGAIN }));
    expect(
      await within(list()).findByRole("link", { name: "Draft ready" }, { timeout: 9000 }),
    ).toHaveAttribute("href", "/notes/n-ready");
    expect(polls).toBeGreaterThan(2);
  }, 20000);
});
