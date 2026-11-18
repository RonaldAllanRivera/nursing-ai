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
} from "./draftingKit";

const DONE = "00000000-0000-4000-8000-00000000aa02";
const detail = demoApi.patientDetails[PATIENT_A];
const BOX = () => screen.getByLabelText("Your note");
const EARLIER = "Your earlier note has its draft.";

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
    await userEvent.click(form().getByRole("button", { name: AGAIN }));
    expect(await form().findByText(EARLIER)).toBeVisible();
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
