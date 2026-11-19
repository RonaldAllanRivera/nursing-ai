import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import { demoApi } from "../mocks/demo-api";
import { renderApp } from "../test/render";
import { server } from "../test/setup";
import { pageStatus } from "../test/status";
import { MOCK_EMAILS } from "../mocks/staff";
import { DEMO_ENDED } from "../session/pin";
import { noteQuery } from "./note";
import { linesInOrder } from "./trace";
import { chooseAndUnlock, DEMO_PIN, demoPinHint } from "../test/signIn";

const NOTE_1 = "00000000-0000-4000-8000-000000000015";
const NOTE_US = "00000000-0000-4000-8000-000000000035";
const SARAH = "Staff nurse · Sarah Navarro, RN";
const EMILY = "Staff nurse · Emily Carter, RN";

type Note = (typeof demoApi.notes)[string];

function demoNote(id: string): Note {
  const found = demoApi.notes[id];
  if (!found) throw new Error(`no demo note ${id}`);
  return structuredClone(found);
}

async function openNote(noteId = NOTE_1, persona = SARAH) {
  const app = await renderApp("/sign-in");
  await chooseAndUnlock(persona);
  await screen.findByRole("heading", { level: 1 });
  await act(() => app.router.navigate({ to: "/notes/$noteId", params: { noteId }, search: {} }));
  await screen.findByRole("heading", { name: "Your note" });
  return app;
}

/** Opens a note whose GET is changed (the writes still go to the mock). */
async function openChanged(
  change: (note: Note) => Note,
  noteId = NOTE_1,
  persona = SARAH,
  before?: () => void,
) {
  const app = await renderApp("/sign-in");
  before?.();
  await chooseAndUnlock(persona);
  await screen.findByRole("heading", { level: 1 });
  server.use(
    http.get("*/api/v1/notes/:id", () =>
      HttpResponse.json(change(demoNote(noteId)), { headers: { ETag: '"v1"' } }),
    ),
  );
  await act(() => app.router.navigate({ to: "/notes/$noteId", params: { noteId }, search: {} }));
  await screen.findByRole("heading", { name: "Your note" });
  return app;
}

const resolveAll = (note: Note) => {
  for (const line of linesInOrder(note.draft)) {
    if (line.status !== "source_found") line.review = "confirmed";
  }
  return note;
};

/** Types the PIN into the sign dialog and presses its Sign note button. */
async function signWithPin(dialog: HTMLElement, pin = DEMO_PIN) {
  await userEvent.type(within(dialog).getByLabelText("Your PIN"), pin);
  await userEvent.click(within(dialog).getByRole("button", { name: "Sign note" }));
}

const line = (name: RegExp) => screen.getByRole("button", { name });
const card = () => within(screen.getByRole("complementary", { name: /came from/ }));
const said = (words: string) =>
  waitFor(() => {
    expect(pageStatus()).toHaveTextContent(words);
  });
const FOCUS = /^Dizziness with low blood pressure/;
const ACTIONS = /Wording is right|Edit line|Undo|Remove line|Put line back|Use \d/;
const PHYSICIAN = /^Physician notified/;

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("acting on a line", () => {
  it("confirming the wording marks the line as checked by you and says so", async () => {
    await openNote();
    await userEvent.click(line(FOCUS));
    await userEvent.click(card().getByRole("button", { name: "Wording is right" }));
    await said("Wording confirmed.");
    expect(line(FOCUS)).toHaveTextContent("Checked by you");
    expect(card().getByText("You confirmed this wording.")).toBeVisible();
    expect(screen.getByText("2 lines need you before you sign.")).toBeVisible();
    expect(card().getByRole("button", { name: "Undo" })).toBeVisible();
    expect(card().getByRole("button", { name: "Edit line" })).toBeVisible();
    expect(card().queryByRole("button", { name: "Wording is right" })).toBeNull();
  });

  it("puts a confirmed line back as the AI wrote it", async () => {
    await openNote();
    await userEvent.click(line(FOCUS));
    await userEvent.click(card().getByRole("button", { name: "Wording is right" }));
    await userEvent.click(await card().findByRole("button", { name: "Undo" }));
    await said("Line put back as the AI wrote it.");
    expect(line(FOCUS)).toHaveTextContent("AI wording — check");
  });

  it("uses the note's number: the line changes, the mark goes, and the line is edited by you", async () => {
    await openNote();
    await userEvent.click(line(/^BP 90\/60 mmHg, HR 121/));
    expect(document.querySelector(".note-text .num-bad")).not.toBeNull();
    await userEvent.click(card().getByRole("button", { name: "Use 112 from your note" }));
    await said("Changed to 112.");
    const fixed = line(/^BP 90\/60 mmHg, HR 112 bpm\./);
    expect(fixed).toHaveTextContent("Edited by you");
    expect(
      card().getByText("You edited this line. Code checked it again when you saved."),
    ).toBeVisible();
    expect(document.querySelector(".num-bad")).toBeNull();
    expect(document.querySelector(".note-text .num-bad")).toBeNull();
  });

  it("removes a line with no source, then puts it back", async () => {
    await openNote();
    await userEvent.click(line(PHYSICIAN));
    expect(card().queryByRole("button", { name: "Edit line" })).toBeNull();
    await userEvent.click(card().getByRole("button", { name: "Remove line" }));
    await said("Line removed.");
    expect(line(PHYSICIAN)).toHaveTextContent("Removed by you");
    expect(
      card().getByText("You removed this line. It won't be in the signed note."),
    ).toBeVisible();
    await userEvent.click(await card().findByRole("button", { name: "Put line back" }));
    await said("Line put back as the AI wrote it.");
    expect(line(PHYSICIAN)).toHaveTextContent("Not in your note");
  });

  it("gives a Focus line with no source Edit line, never Remove line", async () => {
    await openChanged((note) => {
      const focus = note.draft.entries[0]?.focus;
      if (focus) {
        focus.status = "no_source";
        focus.source_quotes = [];
      }
      return note;
    });
    await userEvent.click(line(FOCUS));
    expect(card().getByRole("button", { name: "Edit line" })).toBeVisible();
    expect(card().queryByRole("button", { name: "Remove line" })).toBeNull();
  });

  it("edits a line in a labelled box, saves it and says so", async () => {
    await openNote();
    await userEvent.click(line(FOCUS));
    await userEvent.click(card().getByRole("button", { name: "Edit line" }));
    const box = card().getByRole("textbox", { name: "Edit line" });
    expect(box).toHaveValue("Dizziness with low blood pressure");
    expect(box).toHaveFocus();
    await userEvent.clear(box);
    await userEvent.type(box, "Dizzy, low BP");
    await userEvent.click(card().getByRole("button", { name: "Save line" }));
    await said("Line saved.");
    expect(line(/^Dizzy, low BP/)).toHaveTextContent("Edited by you");
    expect(card().queryByRole("textbox")).toBeNull();
  });

  it("closes the edit box with Cancel and keeps the line as it was", async () => {
    await openNote();
    await userEvent.click(line(FOCUS));
    await userEvent.click(card().getByRole("button", { name: "Edit line" }));
    await userEvent.type(card().getByRole("textbox", { name: "Edit line" }), " more");
    await userEvent.click(card().getByRole("button", { name: "Cancel" }));
    expect(card().queryByRole("textbox")).toBeNull();
    expect(line(FOCUS)).toHaveTextContent("AI wording — check");
    // The focus is put back on the next frame.
    await waitFor(() => {
      expect(card().getByRole("button", { name: "Edit line" })).toHaveFocus();
    });
  });

  it("will not save an empty line, and says what to do", async () => {
    await openNote();
    await userEvent.click(line(FOCUS));
    await userEvent.click(card().getByRole("button", { name: "Edit line" }));
    await userEvent.clear(card().getByRole("textbox", { name: "Edit line" }));
    await userEvent.click(card().getByRole("button", { name: "Save line" }));
    expect(await card().findByRole("alert")).toHaveTextContent(
      "A line needs 1 to 500 characters. Write something, or cancel.",
    );
  });

  it("keeps the typed text after a 412", async () => {
    const app = await openNote();
    await userEvent.click(line(FOCUS));
    await userEvent.click(card().getByRole("button", { name: "Edit line" }));
    const box = card().getByRole("textbox", { name: "Edit line" });
    await userEvent.clear(box);
    await userEvent.type(box, "My own words");
    server.use(
      http.patch("*/api/v1/notes/:id/lines/:lineId", () =>
        HttpResponse.json(
          { type: "about:blank", title: "The note changed", status: 412, code: "stale_version" },
          { status: 412, headers: { "Content-Type": "application/problem+json" } },
        ),
      ),
    );
    await userEvent.click(card().getByRole("button", { name: "Save line" }));
    expect(
      await card().findByText(
        "This note changed somewhere else. Reload to see the latest version. Your text is still here.",
      ),
    ).toBeVisible();
    expect(card().getByRole("textbox", { name: "Edit line" })).toHaveValue("My own words");

    // Reload note fetches the latest note; the edit box and its text stay.
    const reads = vi.fn();
    server.use(
      http.get("*/api/v1/notes/:id", () => {
        reads();
        return HttpResponse.json(demoNote(NOTE_1), { headers: { ETag: '"v3"' } });
      }),
    );
    await userEvent.click(card().getByRole("button", { name: "Reload note" }));
    await waitFor(() => {
      expect(reads).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
      expect(app.queryClient.getQueryData<{ etag: string }>(["note", NOTE_1])?.etag).toBe('"v3"');
    });
    expect(card().getByRole("textbox", { name: "Edit line" })).toHaveValue("My own words");
    await waitFor(() => {
      expect(card().queryByRole("button", { name: "Reload note" })).toBeNull();
    });
  });

  it("says a signed note is locked on a 409 note_locked", async () => {
    await openNote();
    server.use(
      http.patch("*/api/v1/notes/:id/lines/:lineId", () =>
        HttpResponse.json(
          { type: "about:blank", title: "Locked", status: 409, code: "note_locked" },
          { status: 409, headers: { "Content-Type": "application/problem+json" } },
        ),
      ),
    );
    await userEvent.click(line(FOCUS));
    await userEvent.click(card().getByRole("button", { name: "Wording is right" }));
    expect(await card().findByText("This note is locked.")).toBeVisible();
    expect(card().getByRole("button", { name: "Reload note" })).toBeVisible();
  });

  it("says what to do when a change could not be saved", async () => {
    await openNote();
    server.use(http.patch("*/api/v1/notes/:id/lines/:lineId", () => HttpResponse.error()));
    await userEvent.click(line(FOCUS));
    await userEvent.click(card().getByRole("button", { name: "Wording is right" }));
    expect(await card().findByRole("alert")).toHaveTextContent(
      "That change was not saved. Check your connection and try again.",
    );
    expect(line(FOCUS)).toHaveTextContent("AI wording — check");
  });

  it("sends the cached ETag as If-Match, and keeps the new one", async () => {
    const seen: (string | null)[] = [];
    const app = await openNote();
    server.use(
      http.patch("*/api/v1/notes/:id/lines/:lineId", ({ request }) => {
        seen.push(request.headers.get("If-Match"));
        return HttpResponse.json(demoNote(NOTE_1), { headers: { ETag: '"v2"' } });
      }),
    );
    await userEvent.click(line(FOCUS));
    await userEvent.click(card().getByRole("button", { name: "Wording is right" }));
    await said("Wording confirmed.");
    expect(seen).toEqual(['"v1"']);
    expect(app.queryClient.getQueryData<{ etag: string }>(["note", NOTE_1])?.etag).toBe('"v2"');
  });

  it("queues a second action on the note behind the first, and sends the version the first returned", async () => {
    const seen: (string | null)[] = [];
    await openNote();
    server.use(
      http.patch("*/api/v1/notes/:id/lines/:lineId", async ({ request }) => {
        seen.push(request.headers.get("If-Match"));
        const first = seen.length === 1;
        if (first) await delay(250);
        return HttpResponse.json(demoNote(NOTE_1), { headers: { ETag: first ? '"v2"' : '"v3"' } });
      }),
    );
    await userEvent.click(line(FOCUS));
    await userEvent.click(card().getByRole("button", { name: "Wording is right" }));
    // The first PATCH is still out: pick another line and act on it.
    await userEvent.click(line(PHYSICIAN));
    await userEvent.click(card().getByRole("button", { name: "Remove line" }));
    await waitFor(() => {
      expect(seen).toEqual(['"v1"', '"v2"']);
    });
    await said("Line removed.");
    expect(screen.queryByText(/changed somewhere else/)).toBeNull();
  });
});

describe("signing", () => {
  it("opens the dialog once no line is left, and Cancel closes it with the focus back on Sign note", async () => {
    await openChanged(resolveAll);
    const opener = screen.getByRole("button", { name: "Sign note" });
    await userEvent.click(opener);
    const dialog = await screen.findByRole("dialog", { name: "Sign this FDAR note" });
    expect(
      within(dialog).getByText(
        "You're signing as Sarah Navarro, RN. After you sign, the note is locked.",
      ),
    ).toBeVisible();
    expect(within(dialog).getByText("Not in this note:")).toBeVisible();
    expect(within(dialog).getByText(/CBC, Fall risk\. You can still sign\./)).toBeVisible();
    expect(within(dialog).getByLabelText("Your PIN")).toHaveValue("");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    await waitFor(() => {
      expect(opener).toHaveFocus();
    });
  });

  it("closes the dialog with Escape and gives the focus back", async () => {
    await openChanged(resolveAll);
    const opener = screen.getByRole("button", { name: "Sign note" });
    await userEvent.click(opener);
    await screen.findByRole("dialog");
    await userEvent.keyboard("{Escape}");
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    await waitFor(() => {
      expect(opener).toHaveFocus();
    });
  });

  it("leaves the missing sentence out when nothing is missing, and says DAR in a US unit", async () => {
    await openChanged((note) => ({ ...resolveAll(note), checklist: [] }), NOTE_US, EMILY);
    await userEvent.click(screen.getByRole("button", { name: "Sign note" }));
    const dialog = await screen.findByRole("dialog", { name: "Sign this DAR note" });
    expect(within(dialog).queryByText(/Not in this note/)).toBeNull();
  });

  it("signs a fully checked note: the lock, the signer's time and the short hash replace the Sign bar", async () => {
    const app = await openNote();
    const spy = vi.spyOn(app.queryClient, "invalidateQueries");
    await userEvent.click(line(FOCUS));
    await userEvent.click(card().getByRole("button", { name: "Wording is right" }));
    await userEvent.click(line(/^BP 90\/60 mmHg, HR 121/));
    await userEvent.click(card().getByRole("button", { name: "Use 112 from your note" }));
    await userEvent.click(line(PHYSICIAN));
    await userEvent.click(card().getByRole("button", { name: "Remove line" }));
    await said("Line removed.");
    await userEvent.click(screen.getByRole("button", { name: "Sign note" }));
    const dialog = await screen.findByRole("dialog");
    await signWithPin(dialog);

    expect(await screen.findByText(/^Signed by you at \d\d:\d\d\.$/)).toBeVisible();
    expect(screen.getByText("Note hash 9f2c7a41d83b")).toBeVisible();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByText("Signed. This note is locked.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Sign note" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Discard draft" })).toBeNull();
    // Removed lines are not in the record.
    expect(screen.queryByRole("button", { name: PHYSICIAN })).toBeNull();
    // No actions on a signed line.
    await userEvent.click(line(FOCUS));
    expect(card().queryByRole("button", { name: ACTIONS })).toBeNull();
    expect(spy).toHaveBeenCalledWith({ queryKey: ["patient"] });
  });

  it("a 409 review_incomplete jumps to the first listed line", async () => {
    const app = await openChanged(resolveAll);
    server.use(
      http.post("*/api/v1/notes/:id/sign", () =>
        HttpResponse.json(
          {
            type: "about:blank",
            title: "Review is not complete",
            status: 409,
            code: "review_incomplete",
            line_ids: ["e1-D2", "e1-A2"],
          },
          { status: 409, headers: { "Content-Type": "application/problem+json" } },
        ),
      ),
    );
    await userEvent.click(screen.getByRole("button", { name: "Sign note" }));
    const dialog = await screen.findByRole("dialog");
    await signWithPin(dialog);
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    expect(app.router.state.location.search).toEqual({ line: "e1-D2" });
    await waitFor(() => {
      expect(line(/^BP 90\/60 mmHg, HR 121/)).toHaveFocus();
    });
    await said("Check this line before you sign.");
  });

  it("tells the nurse to reload on a 412, inside the dialog", async () => {
    await openChanged(resolveAll);
    server.use(
      http.post("*/api/v1/notes/:id/sign", () =>
        HttpResponse.json(
          { type: "about:blank", title: "The note changed", status: 412, code: "stale_version" },
          { status: 412, headers: { "Content-Type": "application/problem+json" } },
        ),
      ),
    );
    await userEvent.click(screen.getByRole("button", { name: "Sign note" }));
    const dialog = await screen.findByRole("dialog");
    await signWithPin(dialog);
    expect(
      await within(dialog).findByText(
        "This note changed somewhere else. Reload to see the latest version.",
      ),
    ).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "Reload note" })).toBeVisible();
  });
});

describe("signing with your own PIN", () => {
  /** Counts the sign requests, and keeps the last one's body and If-Match. */
  function watchSigns() {
    const seen: { count: number; body: unknown; ifMatch: string | null } = {
      count: 0,
      body: null,
      ifMatch: null,
    };
    server.events.on("request:start", ({ request }) => {
      if (request.method === "POST" && request.url.endsWith("/sign")) {
        seen.count += 1;
        seen.ifMatch = request.headers.get("If-Match");
        void request
          .clone()
          .json()
          .then((body: unknown) => {
            seen.body = body;
          });
      }
    });
    return seen;
  }

  /** Checks every line through the screen, so the mock's own note is ready to sign. */
  async function openSignDialog() {
    const app = await openNote();
    await userEvent.click(line(FOCUS));
    await userEvent.click(card().getByRole("button", { name: "Wording is right" }));
    await userEvent.click(line(/^BP 90\/60 mmHg, HR 121/));
    await userEvent.click(card().getByRole("button", { name: "Use 112 from your note" }));
    await userEvent.click(line(PHYSICIAN));
    await userEvent.click(card().getByRole("button", { name: "Remove line" }));
    await said("Line removed.");
    await userEvent.click(screen.getByRole("button", { name: "Sign note" }));
    const dialog = await screen.findByRole("dialog");
    return { app, dialog };
  }

  afterEach(() => {
    server.events.removeAllListeners();
  });

  it("sends the PIN that was typed, against the cached version", async () => {
    const { app, dialog } = await openSignDialog();
    const seen = watchSigns();
    const cached = app.queryClient.getQueryData(noteQuery(NOTE_1).queryKey)?.etag;
    // A try with another PIN sends that PIN: what is sent is what was typed.
    await signWithPin(dialog, "999999");
    await within(dialog).findByText("Wrong PIN. 4 tries left.");
    await waitFor(() => {
      expect(seen.body).toEqual({ pin: "999999" });
    });
    expect(seen.ifMatch).toBe(cached);
    await signWithPin(dialog);
    expect(await screen.findByText(/^Signed by you at/)).toBeVisible();
    await waitFor(() => {
      expect(seen.body).toEqual({ pin: DEMO_PIN });
    });
    expect(seen.ifMatch).toBe(cached);
  });

  it("keeps the PIN out of TanStack's mutation cache", async () => {
    const { app, dialog } = await openSignDialog();
    await signWithPin(dialog);
    await screen.findByText(/^Signed by you at/);
    await waitFor(() => {
      expect(JSON.stringify(app.queryClient.getMutationCache().getAll())).not.toContain(DEMO_PIN);
    });
  });

  it("does not send fewer than 6 digits, and says what to type", async () => {
    const { dialog } = await openSignDialog();
    const seen = watchSigns();
    await signWithPin(dialog, "1357");
    expect(await within(dialog).findByText("Enter your 6-digit PIN.")).toBeVisible();
    expect(within(dialog).getByLabelText("Your PIN")).toHaveAccessibleDescription(
      expect.stringContaining("Enter your 6-digit PIN."),
    );
    expect(seen.count).toBe(0);
    expect(screen.getByRole("dialog")).toBeVisible();
  });

  it("an Enter held down on the opener lands in an empty PIN field and cannot sign", async () => {
    await openChanged(resolveAll);
    const seen = watchSigns();
    const opener = screen.getByRole("button", { name: "Sign note" });
    opener.focus();
    await userEvent.keyboard("{Enter>}");
    const dialog = await screen.findByRole("dialog");
    await waitFor(() => {
      expect(within(dialog).getByLabelText("Your PIN")).toHaveFocus();
    });
    // The key is still down and repeating: a repeat is not a decision.
    fireEvent.keyDown(within(dialog).getByLabelText("Your PIN"), { key: "Enter", repeat: true });
    await userEvent.keyboard("{/Enter}");
    expect(seen.count).toBe(0);
    expect(within(dialog).queryByText("Enter your 6-digit PIN.")).toBeNull();
    expect(screen.getByRole("dialog")).toBeVisible();
  });

  it("shows a demo person the demo PIN, and ties it to the field", async () => {
    const { dialog } = await openSignDialog();
    expect(within(dialog).getByText(demoPinHint())).toBeVisible();
    expect(within(dialog).getByLabelText("Your PIN")).toHaveAccessibleDescription(
      expect.stringContaining(`Demo PIN: ${DEMO_PIN}`),
    );
  });

  it("does not show the demo PIN to a Google user", async () => {
    await renderApp("/notes/" + NOTE_1, { account: { user: MOCK_EMAILS.phStaff, gate: "open" } }, [
      http.get("*/api/v1/notes/:id", () =>
        HttpResponse.json(resolveAll(demoNote(NOTE_1)), { headers: { ETag: '"v1"' } }),
      ),
    ]);
    await userEvent.click(await screen.findByRole("button", { name: "Sign note" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText("Your PIN")).toBeVisible();
    expect(within(dialog).queryByText(/Demo PIN/)).toBeNull();
  });

  it("signs from the keyboard: type the PIN and press Enter", async () => {
    const { dialog } = await openSignDialog();
    await userEvent.type(within(dialog).getByLabelText("Your PIN"), `${DEMO_PIN}{Enter}`);
    expect(await screen.findByText(/^Signed by you at/)).toBeVisible();
  });

  it("a wrong PIN keeps the dialog open, clears the field and says the tries left", async () => {
    const { dialog } = await openSignDialog();
    await signWithPin(dialog, "999999");
    expect(await within(dialog).findByText("Wrong PIN. 4 tries left.")).toBeVisible();
    const field = within(dialog).getByLabelText("Your PIN");
    expect(field).toHaveValue("");
    await waitFor(() => {
      expect(field).toHaveFocus();
    });
    expect(within(dialog).queryByText(/not saved/)).toBeNull();
    // The right PIN then signs.
    await signWithPin(dialog);
    expect(await screen.findByText(/^Signed by you at/)).toBeVisible();
  });

  it("clears the last try's words, and the field, when the dialog is closed", async () => {
    const { dialog } = await openSignDialog();
    await signWithPin(dialog, "999999");
    await within(dialog).findByText("Wrong PIN. 4 tries left.");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    await userEvent.click(screen.getByRole("button", { name: "Sign note" }));
    const again = await screen.findByRole("dialog");
    expect(within(again).queryByText(/Wrong PIN/)).toBeNull();
    expect(within(again).getByLabelText("Your PIN")).toHaveValue("");
  });

  it("sends a demo person back to sign-in after the fifth wrong PIN", async () => {
    const { dialog } = await openSignDialog();
    for (let i = 0; i < 4; i += 1) {
      await signWithPin(dialog, "999999");
      await within(dialog).findByText(new RegExp(`^Wrong PIN\\. ${String(4 - i)} tr`));
    }
    await signWithPin(dialog, "999999");
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeVisible();
    expect(screen.getByText(DEMO_ENDED)).toBeVisible();
  });
});

const problem = (status: number, code: string, extra: object = {}) =>
  HttpResponse.json(
    { type: "about:blank", title: "Refused", status, code, ...extra },
    { status, headers: { "Content-Type": "application/problem+json" } },
  );

describe("the dialogs open on the safe choice", () => {
  it("puts the focus on the empty PIN field in the sign dialog", async () => {
    await openChanged(resolveAll);
    await userEvent.click(screen.getByRole("button", { name: "Sign note" }));
    const dialog = await screen.findByRole("dialog");
    await waitFor(() => {
      expect(within(dialog).getByLabelText("Your PIN")).toHaveFocus();
    });
  });

  it("puts the focus on Keep draft in the discard dialog", async () => {
    await openNote();
    await userEvent.click(screen.getByRole("button", { name: "Discard draft" }));
    const dialog = await screen.findByRole("dialog");
    await waitFor(() => {
      expect(within(dialog).getByRole("button", { name: "Keep draft" })).toHaveFocus();
    });
  });
});

describe("while a write is under way", () => {
  it("keeps the sign dialog open: Escape and Cancel wait, and the note is signed", async () => {
    await openChanged(resolveAll);
    server.use(
      http.post("*/api/v1/notes/:id/sign", async () => {
        await delay(250);
        return HttpResponse.json(signedNote(), { headers: { ETag: '"v2"' } });
      }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Sign note" }));
    const dialog = await screen.findByRole("dialog");
    await signWithPin(dialog);
    expect(await within(dialog).findByRole("button", { name: "Signing…" })).toBeVisible();
    await userEvent.keyboard("{Escape}");
    const cancel = within(dialog).getByRole("button", { name: "Cancel" });
    expect(cancel).toHaveAttribute("aria-disabled", "true");
    await userEvent.click(cancel);
    expect(screen.getByRole("dialog")).toBeVisible();
    expect(await screen.findByText(/^Signed by you at/)).toBeVisible();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("will not take Cancel in the edit box while the line saves, and says why", async () => {
    await openNote();
    server.use(
      http.patch("*/api/v1/notes/:id/lines/:lineId", async () => {
        await delay(250);
        return HttpResponse.json(demoNote(NOTE_1), { headers: { ETag: '"v2"' } });
      }),
    );
    await userEvent.click(line(FOCUS));
    await userEvent.click(card().getByRole("button", { name: "Edit line" }));
    await userEvent.click(card().getByRole("button", { name: "Save line" }));
    const saving = await card().findByRole("button", { name: "Saving…" });
    expect(saving).toBeVisible();
    const cancel = card().getByRole("button", { name: "Cancel" });
    expect(cancel).toHaveAttribute("aria-disabled", "true");
    await userEvent.click(cancel);
    expect(card().getByRole("textbox", { name: "Edit line" })).toBeVisible();
    await said("Line saved.");
  });

  it("does not open the edit box while a change is saving", async () => {
    await openNote();
    server.use(
      http.patch("*/api/v1/notes/:id/lines/:lineId", async () => {
        await delay(250);
        return HttpResponse.json(demoNote(NOTE_1), { headers: { ETag: '"v2"' } });
      }),
    );
    await userEvent.click(line(FOCUS));
    await userEvent.click(card().getByRole("button", { name: "Wording is right" }));
    await userEvent.click(card().getByRole("button", { name: "Edit line" }));
    expect(card().queryByRole("textbox")).toBeNull();
    await said("Wording confirmed.");
  });

  it("keeps a write's answer when a slower refetch was already under way", async () => {
    const app = await openNote();
    server.use(
      http.get("*/api/v1/notes/:id", async () => {
        await delay(200);
        return HttpResponse.json(demoNote(NOTE_1), { headers: { ETag: '"v1"' } });
      }),
    );
    void app.queryClient.refetchQueries({ queryKey: ["note", NOTE_1] });
    await userEvent.click(line(FOCUS));
    await userEvent.click(card().getByRole("button", { name: "Wording is right" }));
    await said("Wording confirmed.");
    await new Promise((resolve) => setTimeout(resolve, 400));
    expect(line(FOCUS)).toHaveTextContent("Checked by you");
    expect(app.queryClient.getQueryData<{ etag: string }>(["note", NOTE_1])?.etag).toBe('"v2"');
  });
});

function signedNote(): Note {
  const me = Object.values(demoApi.sessions).find((s) => s.display_name === "Sarah Navarro, RN");
  return {
    ...resolveAll(demoNote(NOTE_1)),
    status: "signed",
    version: 2,
    signature: {
      signed_by: me?.user_id ?? "",
      signed_at: "2026-11-11T21:42:00Z",
      content_hash: "0123456789abcdef".repeat(4),
    },
  };
}

describe("after a sign or a discard", () => {
  it("puts the focus on the lock after signing", async () => {
    await openChanged(resolveAll);
    server.use(
      http.post("*/api/v1/notes/:id/sign", () =>
        HttpResponse.json(signedNote(), { headers: { ETag: '"v2"' } }),
      ),
    );
    await userEvent.click(screen.getByRole("button", { name: "Sign note" }));
    const dialog = await screen.findByRole("dialog");
    await signWithPin(dialog);
    const lock = (await screen.findByText(/^Signed by you at/)).closest(".signed");
    await waitFor(() => {
      expect(lock).toHaveFocus();
    });
  });

  it("puts the focus on the answer line after discarding, without a second announcement", async () => {
    await openNote();
    await userEvent.click(screen.getByRole("button", { name: "Discard draft" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Discard draft" }));
    const answer = await screen.findByText("Discarded. This draft won't reach the record.");
    await waitFor(() => {
      expect(answer).toHaveFocus();
    });
    expect(pageStatus()).toHaveTextContent("");
  });

  it("says in the discard dialog that the note changed, and offers Reload note", async () => {
    await openNote();
    server.use(http.post("*/api/v1/notes/:id/discard", () => problem(412, "stale_version")));
    await userEvent.click(screen.getByRole("button", { name: "Discard draft" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Discard draft" }));
    expect(
      await within(dialog).findByText(
        "This note changed somewhere else. Reload to see the latest version.",
      ),
    ).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "Reload note" })).toBeVisible();
  });

  it("says in the discard dialog that the note is locked", async () => {
    await openNote();
    server.use(http.post("*/api/v1/notes/:id/discard", () => problem(409, "note_locked")));
    await userEvent.click(screen.getByRole("button", { name: "Discard draft" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Discard draft" }));
    expect(await within(dialog).findByText("This note is locked.")).toBeVisible();
    expect(within(dialog).getByText("Reload to see it.")).toBeVisible();
  });

  it("keeps the sign dialog open, with words, when review_incomplete lists no line", async () => {
    await openChanged(resolveAll);
    server.use(
      http.post("*/api/v1/notes/:id/sign", () =>
        problem(409, "review_incomplete", { line_ids: [] }),
      ),
    );
    await userEvent.click(screen.getByRole("button", { name: "Sign note" }));
    const dialog = await screen.findByRole("dialog");
    await signWithPin(dialog);
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "Some lines still need a check. Cancel, then look at each flagged line.",
    );
    expect(screen.getByRole("dialog")).toBeVisible();
  });
});

describe("a line with two differing numbers", () => {
  it("offers one button for both numbers and sends one edit", async () => {
    const text = "At 0330, HR 121 bpm, temperature 37.8 °F.";
    const at = (words: string) => {
      const start = Array.from(text.slice(0, text.indexOf(words))).length;
      return { start, end: start + Array.from(words).length };
    };
    await openChanged((note) => {
      const d1 = linesInOrder(note.draft).find((l) => l.id === "e1-D1");
      if (!d1) throw new Error("no D1");
      d1.text = text;
      d1.status = "number_mismatch";
      d1.number_mismatches = [
        {
          kind: "value",
          draft_text: "121",
          draft_span: at("121"),
          note_text: "112",
          note_span: null,
        },
        {
          kind: "unit",
          draft_text: "37.8 °F",
          draft_span: at("37.8 °F"),
          note_text: "37.8",
          note_span: null,
        },
      ];
      return note;
    });
    const bodies: unknown[] = [];
    server.use(
      http.patch("*/api/v1/notes/:id/lines/:lineId", async ({ request }) => {
        bodies.push(await request.json());
        return HttpResponse.json(demoNote(NOTE_1), { headers: { ETag: '"v2"' } });
      }),
    );
    await userEvent.click(line(/^At 0330, HR 121/));
    expect(card().queryByRole("button", { name: /^Use 112 from/ })).toBeNull();
    await userEvent.click(card().getByRole("button", { name: "Use the numbers from your note" }));
    await said("Changed to 112 and 37.8.");
    expect(bodies).toEqual([{ action: "edit", text: "At 0330, HR 112 bpm, temperature 37.8." }]);
  });
});

describe("Escape in the edit box on a small screen", () => {
  it("does not close the drawer or drop the typed text", async () => {
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => false,
    }));
    const app = await openNote();
    await userEvent.click(line(FOCUS));
    await userEvent.click(card().getByRole("button", { name: "Edit line" }));
    await userEvent.type(card().getByRole("textbox", { name: "Edit line" }), " more");
    await userEvent.keyboard("{Escape}");
    expect(app.router.state.location.search).toEqual({ line: "e1-F" });
    expect(card().getByRole("textbox", { name: "Edit line" })).toHaveValue(
      "Dizziness with low blood pressure more",
    );
  });
});

describe("the signed view", () => {
  const signedBy = (userId: string) => (note: Note) => ({
    ...resolveAll(note),
    status: "signed" as const,
    signature: {
      signed_by: userId,
      signed_at: "2026-11-11T21:42:00Z",
      content_hash: "0123456789abcdef".repeat(4),
    },
  });

  it("shows the lock with the time in the facility's zone and the first 12 characters of the hash", async () => {
    const me = Object.values(demoApi.sessions).find((s) => s.display_name === "Sarah Navarro, RN");
    if (!me) throw new Error("no Sarah");
    await openChanged(signedBy(me.user_id));
    expect(await screen.findByText("Signed by you at 05:42.")).toBeVisible();
    expect(screen.getByText("Note hash 0123456789ab")).toBeVisible();
    expect(screen.queryByRole("button", { name: /Sign note|Discard draft/ })).toBeNull();
  });

  it("says only who signed when it was someone else", async () => {
    await openChanged(signedBy("00000000-0000-4000-8000-0000000000aa"));
    expect(await screen.findByText("Signed at 05:42.")).toBeVisible();
  });

  it("uses the facility's clock", async () => {
    await openChanged(
      (note) => ({
        ...signedBy("someone")(note),
        signature: {
          signed_by: "someone",
          signed_at: "2026-11-12T01:42:00Z",
          content_hash: "0123456789abcdef".repeat(4),
        },
      }),
      NOTE_US,
      EMILY,
      () => {
        const facility = structuredClone(demoApi.facilities["us-demo"]);
        if (!facility) throw new Error("no US facility");
        facility.profile.clock = "12h";
        server.use(http.get("*/api/v1/facilities/us-demo", () => HttpResponse.json(facility)));
      },
    );
    // The facility's zone (Pacific) and its 12-hour clock.
    expect(await screen.findByText("Signed at 5:42 PM.")).toBeVisible();
  });
});

describe("discarding", () => {
  it("asks first, and Keep draft changes nothing", async () => {
    await openNote();
    const opener = screen.getByRole("button", { name: "Discard draft" });
    await userEvent.click(opener);
    const dialog = await screen.findByRole("dialog", { name: "Discard this draft?" });
    expect(
      within(dialog).getByText("It won't reach the record. Your typed note stays saved."),
    ).toBeVisible();
    await userEvent.click(within(dialog).getByRole("button", { name: "Keep draft" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    await waitFor(() => {
      expect(opener).toHaveFocus();
    });
    expect(screen.getByText("3 lines need you before you sign.")).toBeVisible();
  });

  it("is never the primary button", async () => {
    await openNote();
    expect(screen.getByRole("button", { name: "Discard draft" })).not.toHaveClass("btn-primary");
    expect(screen.getByRole("button", { name: "Sign note" })).toHaveClass("btn-primary");
  });

  it("discards the draft: it reads as discarded, with no actions", async () => {
    const app = await openNote();
    const spy = vi.spyOn(app.queryClient, "invalidateQueries");
    await userEvent.click(screen.getByRole("button", { name: "Discard draft" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Discard draft" }));
    expect(await screen.findByText("Discarded. This draft won't reach the record.")).toBeVisible();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("button", { name: /Sign note|Discard draft/ })).toBeNull();
    await userEvent.click(line(FOCUS));
    expect(card().queryByRole("button", { name: ACTIONS })).toBeNull();
    expect(spy).toHaveBeenCalledWith({ queryKey: ["patient"] });
  });
});
