import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { components } from "../api/schema";
import { demoApi } from "../mocks/demo-api";
import type { MockOptions } from "../mocks/options";
import { renderApp } from "../test/render";
import { chooseAndUnlock } from "../test/signIn";
import { server } from "../test/setup";

type Schemas = components["schemas"];

const PATIENT_A = "00000000-0000-4000-8000-000000000011";
const AGAIN_URL = "*/api/v1/rough-notes/:id/draft-jobs";
const SARAH = "Staff nurse · Sarah Navarro, RN";
const AGAIN = "Try drafting again";
const HINT = "To save a new note, change the text.";
const SLOW = { timeout: 5000 };

async function openPatientA(
  options: MockOptions = {},
  overrides: Parameters<typeof renderApp>[2] = [],
) {
  const app = await renderApp("/sign-in", options, overrides);
  await chooseAndUnlock(SARAH);
  await userEvent.click(await screen.findByRole("link", { name: /Demo patient A/ }));
  await screen.findByLabelText("Your note");
  return app;
}

const form = () => {
  const found = screen.getByLabelText("Your note").closest("form");
  if (!found) throw new Error("no form");
  return within(found);
};

async function saveAFailedDraft(failure: NonNullable<MockOptions["failDraft"]>) {
  const app = await openPatientA({ failDraft: failure });
  await userEvent.click(screen.getByLabelText("Your note"));
  await userEvent.paste("pt c/o hilo");
  await userEvent.click(screen.getByRole("button", { name: "Save note" }));
  return app;
}

describe("Try drafting again, in the write form", () => {
  it("is the action next to a failure worth another try, with no change-the-text hint", async () => {
    await saveAFailedDraft("provider_error");
    expect(await form().findByRole("button", { name: AGAIN }, SLOW)).toBeEnabled();
    expect(form().getByRole("alert")).toHaveTextContent("The AI service didn't answer.");
    expect(screen.queryByText(HINT)).toBeNull();
    expect(screen.getByLabelText("Your note")).toHaveValue("pt c/o hilo");
  });

  it("is not offered when the same failure would come again, and the hint stays", async () => {
    await saveAFailedDraft("model_refused");
    expect(await screen.findByText(HINT, {}, SLOW)).toBeVisible();
    expect(screen.queryByRole("button", { name: AGAIN })).toBeNull();
  });

  it("follows the new job to the note, like a first draft", { timeout: 15000 }, async () => {
    const { router } = await saveAFailedDraft("invalid_output");
    await userEvent.click(await form().findByRole("button", { name: AGAIN }, SLOW));
    expect(await form().findByText(/Drafting your note\./)).toBeVisible();
    await waitFor(
      () => {
        expect(router.state.location.pathname).toMatch(/^\/notes\//);
      },
      { timeout: 6000 },
    );
  });

  it("sends one request for a double tap", async () => {
    let sent = 0;
    await saveAFailedDraft("provider_error");
    server.use(
      http.post(AGAIN_URL, () => {
        sent += 1;
        return undefined;
      }),
    );
    await userEvent.dblClick(await form().findByRole("button", { name: AGAIN }, SLOW));
    await form().findByText(/Drafting your note\./);
    expect(sent).toBe(1);
  });

  it("says the daily limit is reached when the server does", async () => {
    await saveAFailedDraft("provider_error");
    server.use(
      http.post(AGAIN_URL, () =>
        HttpResponse.json(
          { type: "about:blank", title: "Limit", status: 429, code: "daily_draft_limit" },
          { status: 429 },
        ),
      ),
    );
    await userEvent.click(await form().findByRole("button", { name: AGAIN }, SLOW));
    expect(
      await form().findByText("You've reached today's draft limit. Try again tomorrow."),
    ).toBeVisible();
    expect(form().getByRole("button", { name: AGAIN })).toBeEnabled();
  });

  it("looks at the list again, with no error, when someone already acted", async () => {
    await saveAFailedDraft("provider_error");
    await form().findByRole("button", { name: AGAIN }, SLOW);
    let patientReads = 0;
    server.use(
      http.get("*/api/v1/patients/:id", () => {
        patientReads += 1;
        return undefined;
      }),
      http.post(AGAIN_URL, () =>
        HttpResponse.json(
          { type: "about:blank", title: "Done", status: 409, code: "already_drafted" },
          { status: 409 },
        ),
      ),
    );
    await userEvent.click(form().getByRole("button", { name: AGAIN }));
    await waitFor(() => {
      expect(patientReads).toBeGreaterThan(0);
    });
    expect(
      screen.queryByText("You've reached today's draft limit. Try again tomorrow."),
    ).toBeNull();
    expect(screen.queryByText(/Couldn't start the draft/)).toBeNull();
  });
});

describe("Try drafting again, in the shift list", () => {
  const job = (extra: Partial<Schemas["DraftJobOut"]>): Schemas["DraftJobOut"] => ({
    id: "00000000-0000-4000-8000-000000000f01",
    rough_note_id: "00000000-0000-4000-8000-000000000e01",
    status: "failed",
    failure: "provider_error",
    note_id: null,
    retryable: true,
    ...extra,
  });
  const detail = demoApi.patientDetails[PATIENT_A];

  /** Opens the patient; each read of the list shows the next of these jobs (the last one stays). */
  async function openWith(...sequence: Schemas["DraftJobOut"][]) {
    let reads = 0;
    const notes = (current: Schemas["DraftJobOut"]): Schemas["ShiftNoteOut"][] => [
      {
        rough_note_id: current.rough_note_id,
        written_at: "2026-11-11T14:30:00Z",
        note_status: current.status === "succeeded" ? "draft" : null,
        job: current,
      },
    ];
    await openPatientA({}, [
      http.get("*/api/v1/patients/:id", () => {
        reads += 1;
        return HttpResponse.json({
          ...detail,
          notes: notes(sequence[Math.min(reads, sequence.length) - 1] as Schemas["DraftJobOut"]),
        });
      }),
    ]);
    return () => reads;
  }

  const list = () => screen.getByRole("list", { name: "Notes this shift" });

  it("offers the button on a retryable failure only, with the row's words kept", async () => {
    await openWith(job({}));
    const row = (await within(list()).findAllByRole("listitem"))[0] as HTMLElement;
    expect(row).toHaveTextContent("The AI service didn't answer. Your note is saved.");
    expect(within(row).getByRole("button", { name: AGAIN })).toBeEnabled();
  });

  it("has no button on a failure that would fail the same way", async () => {
    await openWith(job({ failure: "model_refused", retryable: false }));
    const row = (await within(list()).findAllByRole("listitem"))[0] as HTMLElement;
    expect(within(row).queryByRole("button", { name: AGAIN })).toBeNull();
  });

  it(
    "says Drafting while the new job drafts, then offers the draft",
    { timeout: 15000 },
    async () => {
      const queued = job({
        id: "00000000-0000-4000-8000-000000000f02",
        status: "queued",
        failure: null,
        retryable: false,
      });
      const done = { ...queued, status: "succeeded" as const, note_id: "n-ready" };
      await openWith(job({}), queued, done);
      server.use(
        http.post(AGAIN_URL, () => HttpResponse.json(queued, { status: 202 })),
        http.get("*/api/v1/draft-jobs/:id", async () => {
          await delay(500);
          return HttpResponse.json(done);
        }),
      );
      const row = (await within(list()).findAllByRole("listitem"))[0] as HTMLElement;
      await userEvent.click(within(row).getByRole("button", { name: AGAIN }));
      await waitFor(() => {
        expect(within(list()).getAllByRole("listitem")[0]).toHaveTextContent("Drafting");
      });
      expect(within(list()).queryByRole("button", { name: AGAIN })).toBeNull();
      const ready = await within(list()).findByRole(
        "link",
        { name: "Draft ready" },
        { timeout: 6000 },
      );
      expect(ready).toHaveAttribute("href", "/notes/n-ready");
    },
  );

  it("refreshes the list, with no error, when the server says someone already drafted it", async () => {
    const reads = await openWith(job({}));
    server.use(
      http.post(AGAIN_URL, () =>
        HttpResponse.json(
          { type: "about:blank", title: "Done", status: 409, code: "already_drafted" },
          { status: 409 },
        ),
      ),
    );
    const before = reads();
    const row = (await within(list()).findAllByRole("listitem"))[0] as HTMLElement;
    await userEvent.click(within(row).getByRole("button", { name: AGAIN }));
    await waitFor(() => {
      expect(reads()).toBeGreaterThan(before);
    });
    expect(within(list()).queryByRole("alert")).toBeNull();
  });
});

describe("Use the demo note", () => {
  const withDemoNote = (demo_note: string | null) =>
    http.get("*/api/v1/patients/:id", () => {
      const detail = demoApi.patientDetails[PATIENT_A];
      return HttpResponse.json({ ...detail, demo_note });
    });

  it("is not on the page for a patient with no demo note", async () => {
    await openPatientA({}, [withDemoNote(null)]);
    expect(screen.queryByRole("button", { name: "Use the demo note" })).toBeNull();
  });

  it("puts the demo note in an empty box, moves the focus there and saves nothing", async () => {
    let saves = 0;
    await openPatientA({}, [
      withDemoNote("pt c/o hilo since 2am"),
      http.post("*/api/v1/patients/:id/rough-notes", () => {
        saves += 1;
        return undefined;
      }),
    ]);
    await userEvent.click(await screen.findByRole("button", { name: "Use the demo note" }));
    const box = screen.getByLabelText("Your note");
    expect(box).toHaveValue("pt c/o hilo since 2am");
    expect(box).toHaveFocus();
    expect(screen.getByRole("button", { name: "Save note" })).toBeEnabled();
    expect(saves).toBe(0);
  });

  it("asks before replacing what she typed, and keeps it on Keep my note", async () => {
    await openPatientA({}, [withDemoNote("the demo words")]);
    await userEvent.click(screen.getByLabelText("Your note"));
    await userEvent.paste("my own words");
    await userEvent.click(await screen.findByRole("button", { name: "Use the demo note" }));
    const dialog = await screen.findByRole("dialog");
    expect(screen.getByLabelText("Your note")).toHaveValue("my own words");
    await userEvent.click(within(dialog).getByRole("button", { name: "Keep my note" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    expect(screen.getByLabelText("Your note")).toHaveValue("my own words");
    expect(screen.getByLabelText("Your note")).toHaveFocus();
  });

  it("replaces it after she confirms, and focuses the box", async () => {
    await openPatientA({}, [withDemoNote("the demo words")]);
    await userEvent.click(screen.getByLabelText("Your note"));
    await userEvent.paste("my own words");
    await userEvent.click(await screen.findByRole("button", { name: "Use the demo note" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Replace my note" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    expect(screen.getByLabelText("Your note")).toHaveValue("the demo words");
    expect(screen.getByLabelText("Your note")).toHaveFocus();
  });
});
