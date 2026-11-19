import { act, screen, waitFor } from "@testing-library/react";
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
  problem,
  rowFor,
  saveAFailedDraft,
  type Schemas,
} from "./draftingKit";

const DONE = "00000000-0000-4000-8000-00000000aa02";
const NEWER = "00000000-0000-4000-8000-00000000aa09";
const detail = demoApi.patientDetails[PATIENT_A];
const BOX = () => screen.getByLabelText("Your note");
const EARLIER = "Your earlier note has its draft.";
const EARLIER_DRAFTING = "Your earlier note is being drafted again.";

/** The form's polite live region: always on the page, so a line that comes into it is read out. */
const politeRegion = () => {
  const found = BOX().closest("form")?.querySelector('[aria-live="polite"]');
  if (!(found instanceof HTMLElement)) throw new Error("no polite region in the form");
  return found;
};

/** The earlier note, drafted somewhere else: its newest job is a finished draft. */
const draftedElsewhere = (roughNote: string) =>
  rowFor(
    job({
      id: DONE,
      rough_note_id: roughNote,
      status: "succeeded",
      failure: null,
      retryable: false,
      note_id: "n-late",
    }),
  );

async function editTheText() {
  await userEvent.click(BOX());
  await userEvent.paste(" more");
}

describe("after she has changed the text of a note whose draft failed", () => {
  it("makes Save note the one primary action, and Try drafting again secondary", async () => {
    await saveAFailedDraft("provider_error");
    const again = await form().findByRole("button", { name: AGAIN }, SLOW);
    // Untouched text: re-drafting the saved note is the main thing to do.
    expect(again).toHaveClass("bg-primary");
    expect(form().getByRole("button", { name: "Save note" })).not.toHaveClass("bg-primary");
    await editTheText();
    expect(form().getByRole("button", { name: "Save note" })).toHaveClass("bg-primary");
    expect(form().getByRole("button", { name: AGAIN })).not.toHaveClass("bg-primary");
  });

  it("drops the old failure and the button, and says the earlier note has its draft, when the server says so", async () => {
    let roughNote = "";
    let posts = 0;
    await saveAFailedDraft("provider_error");
    await form().findByRole("button", { name: AGAIN }, SLOW);
    await editTheText();
    server.use(
      http.post(AGAIN_URL, ({ params }) => {
        posts += 1;
        roughNote = String(params["id"]);
        return HttpResponse.json(problem(409, "already_drafted"), { status: 409 });
      }),
      http.get("*/api/v1/patients/:id", () =>
        roughNote === ""
          ? undefined
          : HttpResponse.json({ ...detail, notes: [draftedElsewhere(roughNote)] }),
      ),
    );
    const region = politeRegion();
    await userEvent.click(form().getByRole("button", { name: AGAIN }));
    expect(await form().findByText(EARLIER)).toBeVisible();
    // The alert went and the cursor is in the box: the polite region says what happened.
    expect(region).toHaveTextContent(EARLIER);
    expect(BOX()).toHaveFocus();
    expect(form().queryByRole("button", { name: AGAIN })).toBeNull();
    expect(form().queryByRole("alert")).toBeNull();
    expect(posts).toBe(1);
    expect(BOX()).toHaveValue("pt c/o hilo more");
  }, 20000);

  it("does the same when the list shows the note's newest job past failed, with a link to it", async () => {
    let roughNote = "";
    const { queryClient } = await saveAFailedDraft("provider_error");
    await form().findByRole("button", { name: AGAIN }, SLOW);
    await editTheText();
    // The earlier note's id is read from the list the page already has.
    server.use(
      http.get("*/api/v1/patients/:id", () =>
        roughNote === ""
          ? undefined
          : HttpResponse.json({ ...detail, notes: [draftedElsewhere(roughNote)] }),
      ),
    );
    const cached = queryClient.getQueryData<{ notes: { rough_note_id: string }[] }>([
      "patient",
      PATIENT_A,
    ]);
    roughNote = cached?.notes[0]?.rough_note_id ?? "";
    expect(roughNote).not.toBe("");
    await act(() => queryClient.invalidateQueries({ queryKey: ["patient", PATIENT_A] }));
    expect(await form().findByText(EARLIER)).toBeVisible();
    expect(form().queryByRole("button", { name: AGAIN })).toBeNull();
    expect(form().getByRole("link", { name: "Open it" })).toHaveAttribute("href", "/notes/n-late");
  }, 20000);
});

describe("the earlier note's newest job, while she writes the next note", () => {
  /** Saves a failed draft, edits the text, and has the list name a newer job for the earlier note. */
  async function newerJobInTheList() {
    const { queryClient } = await saveAFailedDraft("provider_error");
    await form().findByRole("button", { name: AGAIN }, SLOW);
    await editTheText();
    const cached = queryClient.getQueryData<{ notes: { rough_note_id: string }[] }>([
      "patient",
      PATIENT_A,
    ]);
    const roughNote = cached?.notes[0]?.rough_note_id ?? "";
    expect(roughNote).not.toBe("");
    let newest = job({
      id: NEWER,
      rough_note_id: roughNote,
      status: "running",
      failure: null,
      retryable: false,
    });
    server.use(
      http.get("*/api/v1/patients/:id", () =>
        HttpResponse.json({ ...detail, notes: [rowFor(newest)] }),
      ),
    );
    /** The list now says this about the earlier note's newest job. */
    const listSays = async (next: Partial<Schemas["DraftJobOut"]>) => {
      newest = { ...newest, ...next };
      await act(() => queryClient.invalidateQueries({ queryKey: ["patient", PATIENT_A] }));
    };
    return { listSays };
  }

  it("says it is being drafted again while that job runs, then that it has its draft", async () => {
    const { listSays } = await newerJobInTheList();
    await listSays({ status: "running" });
    expect(await form().findByText(EARLIER_DRAFTING)).toBeVisible();
    expect(form().queryByText(EARLIER)).toBeNull();
    expect(form().queryByRole("button", { name: AGAIN })).toBeNull();
    expect(form().queryByRole("alert")).toBeNull();
    await listSays({ status: "succeeded", note_id: "n-late" });
    expect(await form().findByText(EARLIER)).toBeVisible();
    expect(form().queryByText(EARLIER_DRAFTING)).toBeNull();
    expect(form().getByRole("link", { name: "Open it" })).toHaveAttribute("href", "/notes/n-late");
  }, 20000);

  it("brings the failure back, in that job's own words, when it fails too", async () => {
    const { listSays } = await newerJobInTheList();
    await listSays({ status: "running" });
    expect(await form().findByText(EARLIER_DRAFTING)).toBeVisible();
    await listSays({ status: "failed", failure: "invalid_output", retryable: true });
    expect(await form().findByRole("alert")).toHaveTextContent(
      "The AI's draft failed the app's checks, so it wasn't kept. Your note is saved.",
    );
    expect(form().queryByText(EARLIER_DRAFTING)).toBeNull();
    expect(form().queryByText(EARLIER)).toBeNull();
    expect(form().getByRole("button", { name: AGAIN })).toBeVisible();
  }, 20000);

  it("does not offer Try drafting again when that newer failure is not worth another try", async () => {
    const { listSays } = await newerJobInTheList();
    await listSays({ status: "failed", failure: "model_refused", retryable: false });
    expect(await form().findByRole("alert")).toHaveTextContent(
      "The AI declined to draft this note. Your note is saved.",
    );
    expect(form().queryByRole("button", { name: AGAIN })).toBeNull();
  }, 20000);

  it("is said in a polite live region that was already on the page", async () => {
    const { listSays } = await newerJobInTheList();
    const before = politeRegion();
    await listSays({ status: "running" });
    await waitFor(() => {
      expect(before).toHaveTextContent(EARLIER_DRAFTING);
    });
    await listSays({ status: "succeeded", note_id: "n-late" });
    await waitFor(() => {
      expect(before).toHaveTextContent(EARLIER);
    });
    expect(politeRegion()).toBe(before);
  }, 20000);
});

describe("while a new note is saving", () => {
  it("takes the last note's failure and its Try drafting again away", async () => {
    await saveAFailedDraft("provider_error");
    await form().findByRole("button", { name: AGAIN }, SLOW);
    server.use(
      http.post("*/api/v1/patients/:id/rough-notes", async () => {
        await delay(800);
        return undefined;
      }),
    );
    await editTheText();
    await userEvent.click(screen.getByRole("button", { name: "Save note" }));
    expect(await screen.findByText("Saving your note…")).toBeVisible();
    expect(form().queryByRole("button", { name: AGAIN })).toBeNull();
    expect(form().queryByText(/The AI service didn't answer/)).toBeNull();
    await waitFor(() => {
      expect(screen.queryByText("Saving your note…")).toBeNull();
    });
  }, 20000);
});
