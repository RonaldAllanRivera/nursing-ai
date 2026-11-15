import { onlineManager } from "@tanstack/react-query";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { components } from "../api/schema";
import { demoApi } from "../mocks/demo-api";
import { renderApp } from "../test/render";
import { server } from "../test/setup";

type Schemas = components["schemas"];

const PATIENT_A = "00000000-0000-4000-8000-000000000011";
const ROUGH_URL = "*/api/v1/patients/:id/rough-notes";

async function openPatientA(persona = "Staff nurse · Sarah Navarro, RN") {
  const app = await renderApp("/sign-in");
  await userEvent.click(await screen.findByRole("button", { name: persona }));
  await userEvent.click(await screen.findByRole("link", { name: /Demo patient A/ }));
  await screen.findByLabelText("Your note");
  return app;
}

async function typeNote(text: string) {
  const box = screen.getByLabelText("Your note");
  await userEvent.clear(box);
  await userEvent.click(box);
  await userEvent.paste(text);
}

const save = () => userEvent.click(screen.getByRole("button", { name: "Save note" }));

/** Records each POST's key and text; answers with `answer(count)`, or falls through to the mock when it returns undefined. */
function recordPosts(answer: (count: number) => Response | undefined) {
  const keys: string[] = [];
  server.use(
    http.post(ROUGH_URL, ({ request }) => {
      keys.push(request.headers.get("Idempotency-Key") ?? "");
      return answer(keys.length);
    }),
  );
  return keys;
}

describe("patient page", () => {
  it("shows the bed tab, the name with the Synthetic tag, the age, sex and ward, and the shift", async () => {
    await openPatientA();
    expect(await screen.findByRole("heading", { name: "Demo patient A" })).toBeVisible();
    expect(screen.getByText("Bed")).toBeVisible();
    expect(screen.getByText("12")).toBeVisible();
    expect(screen.getByText("Synthetic")).toBeVisible();
    expect(screen.getByText("64 F, Medical Ward")).toBeVisible();
    expect(within(screen.getByRole("main")).getByText("Shift 10-6")).toBeVisible();
    expect(screen.getByText(/22:00 11 Nov to 06:00 12 Nov 2026/)).toBeVisible();
    expect(
      screen.getByText("No notes yet this shift. Write the first one in Your note."),
    ).toBeVisible();
  });

  it("uses the unit's words for a US patient", async () => {
    const app = await renderApp("/sign-in");
    await userEvent.click(
      await screen.findByRole("button", { name: "Staff nurse · Emily Carter, RN" }),
    );
    await userEvent.click(await screen.findByRole("link", { name: /Demo patient C/ }));
    expect(await screen.findByText("Room")).toBeVisible();
    expect(within(screen.getByRole("main")).getByText("Shift 7a-7p")).toBeVisible();
    expect(app.router.state.location.pathname).toMatch(/^\/patients\//);
  });

  it("can't save an empty or spaces-only note", async () => {
    await openPatientA();
    const button = screen.getByRole("button", { name: "Save note" });
    expect(button).toBeDisabled();
    await typeNote("    ");
    expect(button).toBeDisabled();
    await typeNote("pt c/o hilo");
    expect(button).toBeEnabled();
  });

  it("says how many characters are left only near the limit", async () => {
    await openPatientA();
    await typeNote("a".repeat(100));
    expect(screen.queryByText(/characters? left/)).not.toBeInTheDocument();
    await typeNote("a".repeat(3900));
    expect(screen.getByText("100 characters left")).toBeVisible();
    await typeNote("a".repeat(4001));
    expect(screen.getByText("1 character too many. Shorten your note to save it.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Save note" })).toBeDisabled();
  });

  it("saves the note, follows the draft and goes to the note", async () => {
    const { router } = await openPatientA();
    await typeNote("pt c/o hilo since 2am");
    await save();
    expect(
      await screen.findByText("Drafting your note. This usually takes a few seconds."),
    ).toBeVisible();
    await waitFor(
      () => {
        expect(router.state.location.pathname).toBe(
          `/notes/${demoApi.jobs[demoApi.jobForPatient[PATIENT_A] ?? ""]?.note_id ?? ""}`,
        );
      },
      { timeout: 4000 },
    );
    expect(await screen.findByRole("heading", { name: /Note / })).toBeVisible();
  });

  it("reuses the idempotency key when it retries", async () => {
    await openPatientA();
    const keys = recordPosts((count) =>
      count === 1 ? HttpResponse.json({}, { status: 500 }) : undefined,
    );
    await typeNote("pt c/o hilo");
    await save();
    await waitFor(() => {
      expect(keys).toHaveLength(2);
    });
    expect(keys[0]).toBeTruthy();
    expect(keys[1]).toBe(keys[0]);
  });

  it("shows the server message and a Try again that reuses the key", async () => {
    await openPatientA();
    const keys = recordPosts((count) => (count <= 3 ? HttpResponse.error() : undefined));
    await typeNote("pt c/o hilo");
    await save();
    expect(
      await screen.findByText("Couldn't reach the server. Your note is still here."),
    ).toBeVisible();
    expect(keys).toHaveLength(3);
    expect(screen.getByLabelText("Your note")).toHaveValue("pt c/o hilo");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findByText("Drafting your note. This usually takes a few seconds.");
    expect(keys).toHaveLength(4);
    expect(new Set(keys).size).toBe(1);
  });

  it("makes a new key when the text changes after a failure", async () => {
    await openPatientA();
    const keys = recordPosts((count) =>
      count <= 3 ? HttpResponse.json({}, { status: 503 }) : undefined,
    );
    await typeNote("pt c/o hilo");
    await save();
    await screen.findByRole("button", { name: "Try again" });
    await typeNote("pt c/o hilo since 2am");
    await save();
    await screen.findByText("Drafting your note. This usually takes a few seconds.");
    expect(keys).toHaveLength(4);
    expect(keys[3]).not.toBe(keys[0]);
    expect(new Set(keys.slice(0, 3)).size).toBe(1);
  });

  it("never retries a 4xx", async () => {
    await openPatientA();
    const keys = recordPosts(() => HttpResponse.json({ code: "forbidden" }, { status: 403 }));
    await typeNote("pt c/o hilo");
    await save();
    expect(
      await screen.findByText("The note was not accepted. Your note is still here."),
    ).toBeVisible();
    expect(keys).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save note" })).toBeEnabled();
  });

  it("shows the budget message and keeps the note", async () => {
    const { router } = await openPatientA();
    server.use(
      http.get("*/api/v1/draft-jobs/:id", ({ params }) =>
        HttpResponse.json<Schemas["DraftJobOut"]>({
          id: String(params["id"]),
          rough_note_id: "00000000-0000-4000-8000-000000000013",
          status: "failed",
          failure: "ai_budget_reached",
          note_id: null,
        }),
      ),
    );
    await typeNote("pt c/o hilo");
    await save();
    expect(await screen.findByText("Monthly AI budget reached. Your note is saved.")).toBeVisible();
    expect(screen.getByLabelText("Your note")).toHaveValue("pt c/o hilo");
    expect(router.state.location.pathname).toMatch(/^\/patients\//);
  });

  describe("after a failed draft", () => {
    const failJob = () => {
      server.use(
        http.get("*/api/v1/draft-jobs/:id", ({ params }) =>
          HttpResponse.json<Schemas["DraftJobOut"]>({
            id: String(params["id"]),
            rough_note_id: "00000000-0000-4000-8000-000000000013",
            status: "failed",
            failure: "provider_error",
            note_id: null,
          }),
        ),
      );
    };

    it("keeps Save note disabled for the same text, and says what to do", async () => {
      await openPatientA();
      failJob();
      const keys = recordPosts(() => undefined);
      await typeNote("pt c/o hilo");
      await save();
      expect(
        await screen.findByText("The AI service didn't answer. Your note is saved."),
      ).toBeVisible();
      expect(screen.getByText("To save a new note, change the text.")).toBeVisible();
      expect(screen.getByRole("button", { name: "Save note" })).toBeDisabled();
      expect(screen.getByLabelText("Your note")).toHaveValue("pt c/o hilo");
      expect(keys).toHaveLength(1);
    });

    it("enables Save note again after an edit and sends a new key", async () => {
      await openPatientA();
      failJob();
      const keys = recordPosts(() => undefined);
      await typeNote("pt c/o hilo");
      await save();
      await screen.findByText("To save a new note, change the text.");
      await typeNote("pt c/o hilo since 2am");
      expect(screen.queryByText("To save a new note, change the text.")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Save note" })).toBeEnabled();
      await save();
      await waitFor(() => {
        expect(keys).toHaveLength(2);
      });
      expect(keys[1]).not.toBe(keys[0]);
    });

    it("refreshes the patient so the saved note shows in this shift's list", async () => {
      await openPatientA();
      failJob();
      let gets = 0;
      server.use(
        http.get("*/api/v1/patients/:id", () => {
          gets += 1;
          return undefined;
        }),
      );
      await typeNote("pt c/o hilo");
      await save();
      await screen.findByText("To save a new note, change the text.");
      await waitFor(() => {
        expect(gets).toBeGreaterThan(0);
      });
    });
  });

  it("invalidates the patient when the draft is ready, for when she comes back", async () => {
    const { router, queryClient } = await openPatientA();
    await typeNote("pt c/o hilo");
    await save();
    await waitFor(
      () => {
        expect(router.state.location.pathname).toMatch(/^\/notes\//);
      },
      { timeout: 4000 },
    );
    expect(queryClient.getQueryState(["patient", PATIENT_A])?.isInvalidated).toBe(true);
  });

  it("holds the text still while the note is saving and drafting", async () => {
    await openPatientA();
    await typeNote("pt c/o hilo");
    await save();
    await screen.findByText("Drafting your note. This usually takes a few seconds.");
    const box = screen.getByLabelText("Your note");
    expect(box).toHaveAttribute("readonly");
    expect(box).toHaveAttribute("aria-readonly", "true");
    await userEvent.type(box, " more");
    expect(box).toHaveValue("pt c/o hilo");
  });

  it("says it is saving while the request is out", async () => {
    await openPatientA();
    server.use(
      http.post(ROUGH_URL, async () => {
        await delay(300);
        return undefined;
      }),
    );
    await typeNote("pt c/o hilo");
    await save();
    expect(await screen.findByText("Saving your note…")).toBeVisible();
    await screen.findByText("Drafting your note. This usually takes a few seconds.");
  });

  it("says it is waiting for the network when the browser is offline", async () => {
    await openPatientA();
    await typeNote("pt c/o hilo");
    act(() => {
      onlineManager.setOnline(false);
    });
    try {
      await save();
      expect(
        await screen.findByText("Waiting for the network. Your note is still here."),
      ).toBeVisible();
    } finally {
      act(() => {
        onlineManager.setOnline(true);
      });
    }
    await screen.findByText("Drafting your note. This usually takes a few seconds.");
  });

  it("stops following a draft the server can't find, and says so", async () => {
    await openPatientA();
    server.use(
      http.get("*/api/v1/draft-jobs/:id", () =>
        HttpResponse.json({ code: "not_found", status: 404, title: "Not found" }, { status: 404 }),
      ),
    );
    await typeNote("pt c/o hilo");
    await save();
    expect(
      await screen.findByText(
        "Couldn't find the draft. Your note is saved. Reload the page to see where it is.",
      ),
    ).toBeVisible();
    expect(screen.getByLabelText("Your note")).not.toHaveAttribute("readonly");
  });

  it("keeps the typed note when a refetch of the patient fails", async () => {
    const { queryClient } = await openPatientA();
    await typeNote("pt c/o hilo");
    server.use(http.get("*/api/v1/patients/:id", () => HttpResponse.json({}, { status: 500 })));
    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: ["patient"] });
    });
    await waitFor(() => {
      expect(queryClient.getQueryState(["patient", PATIENT_A])?.status).toBe("error");
    });
    expect(screen.getByLabelText("Your note")).toHaveValue("pt c/o hilo");
    expect(screen.getByRole("heading", { name: "Demo patient A" })).toBeVisible();
  });

  it("follows a shift change made in the header", async () => {
    await openPatientA();
    const main = within(screen.getByRole("main"));
    expect(main.getByText("Shift 10-6")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Change shift" }));
    await userEvent.click(await screen.findByRole("button", { name: /^2-10/ }));
    expect(await main.findByText("Shift 2-10")).toBeVisible();
    expect(main.getByText(/14:00 to 22:00 11 Nov 2026/)).toBeVisible();
  });

  it("lists this shift's notes with their status, and links a ready draft", async () => {
    const job = (status: Schemas["JobStatus"], extra: Partial<Schemas["DraftJobOut"]> = {}) => ({
      id: "j",
      rough_note_id: "r",
      status,
      failure: null,
      note_id: null,
      ...extra,
    });
    const detail = demoApi.patientDetails[PATIENT_A];
    if (!detail) throw new Error("no detail");
    const notes: Schemas["ShiftNoteOut"][] = [
      {
        rough_note_id: "1",
        written_at: "2026-11-11T14:30:00Z",
        note_status: null,
        job: job("running"),
      },
      {
        rough_note_id: "2",
        written_at: "2026-11-11T15:30:00Z",
        note_status: "draft",
        job: job("succeeded", { note_id: "n-ready" }),
      },
      {
        rough_note_id: "3",
        written_at: "2026-11-11T16:30:00Z",
        note_status: "signed",
        job: job("succeeded", { note_id: "n-signed" }),
      },
      {
        rough_note_id: "4",
        written_at: "2026-11-11T17:30:00Z",
        note_status: "discarded",
        job: job("succeeded", { note_id: "n-gone" }),
      },
      {
        rough_note_id: "5",
        written_at: "2026-11-11T18:30:00Z",
        note_status: null,
        job: job("failed", { failure: "model_refused" }),
      },
    ];
    const app = await renderApp("/sign-in");
    server.use(http.get("*/api/v1/patients/:id", () => HttpResponse.json({ ...detail, notes })));
    await userEvent.click(
      await screen.findByRole("button", { name: "Staff nurse · Sarah Navarro, RN" }),
    );
    await userEvent.click(await screen.findByRole("link", { name: /Demo patient A/ }));
    const list = await screen.findByRole("list", { name: "Notes this shift" });
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(5);
    expect(items[0]).toHaveTextContent("22:30");
    expect(items[0]).toHaveTextContent("Drafting");
    expect(items[1]).toHaveTextContent("Draft ready");
    expect(items[2]).toHaveTextContent("Signed");
    expect(items[3]).toHaveTextContent("Discarded");
    expect(items[4]).toHaveTextContent("The AI declined to draft this note. Your note is saved.");
    expect(within(items[1] as HTMLElement).getByRole("link")).toHaveAttribute(
      "href",
      "/notes/n-ready",
    );
    expect(within(items[2] as HTMLElement).getByRole("link")).toHaveAttribute(
      "href",
      "/notes/n-signed",
    );
    expect(within(items[0] as HTMLElement).queryByRole("link")).not.toBeInTheDocument();
    expect(within(items[3] as HTMLElement).queryByRole("link")).not.toBeInTheDocument();
    expect(app.router.state.location.pathname).toBe(`/patients/${PATIENT_A}`);
  });

  it("says so when the patient does not load", async () => {
    await renderApp("/sign-in");
    server.use(http.get("*/api/v1/patients/:id", () => HttpResponse.json({}, { status: 500 })));
    await userEvent.click(
      await screen.findByRole("button", { name: "Staff nurse · Sarah Navarro, RN" }),
    );
    await userEvent.click(await screen.findByRole("link", { name: /Demo patient A/ }));
    expect(
      await screen.findByText("This patient did not load. Go back and try again."),
    ).toBeVisible();
  });
});
