import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import { demoApi } from "../mocks/demo-api";
import { renderApp } from "../test/render";
import { linesInOrder } from "./trace";
import { server } from "../test/setup";

const NOTE_1 = "00000000-0000-4000-8000-000000000015";
const NOTE_2 = "00000000-0000-4000-8000-000000000025";
const NOTE_US = "00000000-0000-4000-8000-000000000035";
const SARAH = "Staff nurse · Sarah Navarro, RN";
const EMILY = "Staff nurse · Emily Carter, RN";

async function signIn(persona = SARAH) {
  const app = await renderApp("/sign-in");
  await userEvent.click(await screen.findByRole("button", { name: persona }));
  await screen.findByRole("heading", { level: 1 });
  return app;
}

type App = Awaited<ReturnType<typeof signIn>>;

/** Goes to the note (optionally with a line already selected). */
function goToNote(app: App, noteId: string, search: { line?: string } = {}) {
  return act(() => app.router.navigate({ to: "/notes/$noteId", params: { noteId }, search }));
}

/** Signs in and opens the note, once the trace view has loaded. */
async function openNote(noteId: string, search: { line?: string } = {}, persona = SARAH) {
  const app = await signIn(persona);
  await goToNote(app, noteId, search);
  await screen.findByRole("heading", { name: "Your note" });
  return app;
}

/** The mock API's answer for a note is replaced after sign-in (renderApp's own handlers go first otherwise). */
async function openWith(
  change: (note: Note) => Note,
  status = 200,
  search: { line?: string } = {},
) {
  const app = await signIn();
  server.use(
    http.get("*/api/v1/notes/:id", ({ params }) =>
      status === 200
        ? HttpResponse.json(change(structuredClone(demoNote(String(params["id"])))), {
            headers: { ETag: '"v1"' },
          })
        : HttpResponse.json({}, { status }),
    ),
  );
  await goToNote(app, NOTE_1, search);
  return app;
}

function demoNote(id: string) {
  const found = demoApi.notes[id];
  if (!found) throw new Error(`no demo note ${id}`);
  return found;
}

type Note = (typeof demoApi.notes)[string];

const noteText = () => {
  const el = document.querySelector<HTMLElement>(".note-text");
  if (!el) throw new Error("no note text");
  return el;
};
const lineButton = (name: RegExp | string) =>
  screen.getByRole("button", { name: typeof name === "string" ? new RegExp(name) : name });

/** jsdom has no matchMedia: say whether the screen is wide (960 px and up) or not. */
function mockScreen(initiallyWide: boolean) {
  let wide = initiallyWide;
  const listeners = new Set<() => void>();
  vi.stubGlobal("matchMedia", (query: string) => ({
    get matches() {
      return query === "(min-width: 960px)" ? wide : false;
    },
    media: query,
    onchange: null,
    addEventListener: (_type: string, listener: () => void) => listeners.add(listener),
    removeEventListener: (_type: string, listener: () => void) => listeners.delete(listener),
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
  }));
  /** The window is resized across 960 px: the query changes and its listeners hear it. */
  return (next: boolean) => {
    wide = next;
    act(() => {
      listeners.forEach((listener) => {
        listener();
      });
    });
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the trace view", () => {
  it("shows the header, the typed time, the draft's heading and the answer", async () => {
    await openNote(NOTE_1);
    expect(await screen.findByRole("heading", { name: /^Demo patient A/, level: 1 })).toBeVisible();
    expect(screen.getByText("Synthetic")).toBeVisible();
    expect(
      screen.getByText(
        "64 F, Medical Ward. FDAR note for the 10-6 shift, 22:00 11 Nov to 06:00 12 Nov 2026.",
      ),
    ).toBeVisible();
    expect(screen.getByText("Typed at 05:10. The AI never changes it.")).toBeVisible();
    expect(screen.getByRole("heading", { name: "FDAR draft" })).toBeVisible();
    expect(
      screen.getByText("Written by AI, checked by code. Tap a line to see the words it came from."),
    ).toBeVisible();
    expect(screen.getByText("3 lines need you before you sign.")).toBeVisible();
    expect(noteText()).toHaveTextContent(/^pt c\/o hilo since 2am, BP 90\/60 HR 112\./);
    expect(
      screen.getByText(/Tap a line in the draft\. The words it came from light up in your note/),
    ).toBeVisible();
  });

  it("counts the lines for each of the four statuses in the key", async () => {
    await openNote(NOTE_1);
    const key = screen.getByRole("list", { name: "Line checks in this draft" });
    const items = within(key)
      .getAllByRole("listitem")
      .map((li) => li.textContent);
    expect(items).toEqual([
      "Source found 6",
      "AI wording — check 1",
      "Number differs 1",
      "Not in your note 1",
    ]);
  });

  it("shows a line's words and its status, and a row for each entry", async () => {
    await openNote(NOTE_2);
    expect(await screen.findAllByText("Not written — left empty")).toHaveLength(1);
    expect(screen.getByRole("button", { name: /^Disturbed sleep/ })).toBeVisible();
    expect(screen.getByRole("button", { name: /^Fever/ })).toBeVisible();
    expect(screen.getAllByText(/^12 Nov/)).toHaveLength(2);
  });

  it("says DAR in a US unit, with the time in the shift's zone", async () => {
    await openNote(NOTE_US, {}, EMILY);
    expect(await screen.findByRole("heading", { name: "DAR draft" })).toBeVisible();
    expect(screen.getByText("Typed at 10:15. The AI never changes it.")).toBeVisible();
  });

  it("lists the checklist: a missing item with a box, a found one with the words from the note", async () => {
    await openNote(NOTE_1);
    const list = within(screen.getByRole("region", { name: "Missing from this note" }));
    const items = list.getAllByRole("listitem");
    expect(items.map((li) => li.textContent)).toEqual([
      "IV line, left armIn your note: “IVF”",
      "CBCNot in your note.",
      "Fall riskNot in your note.",
    ]);
  });

  it("keeps the note's ETag with the note, for the changes that come next", async () => {
    const app = await openNote(NOTE_1);
    const cached = app.queryClient.getQueryData<{ etag: string | null }>(["note", NOTE_1]);
    expect(cached?.etag).toBe('"v1"');
  });

  it('selecting demo-1\'s D2 line highlights "BP 90/60 HR 112" with "112" marked', async () => {
    const app = await openNote(NOTE_1);
    await userEvent.click(lineButton(/^BP 90\/60 mmHg, HR 121 bpm\./));

    const marks = noteText().querySelectorAll("mark.hl");
    expect(marks).toHaveLength(1);
    expect(marks[0]).toHaveTextContent("BP 90/60 HR 112");
    expect(marks[0]?.querySelector(".num-bad")).toHaveTextContent("112");
    expect(app.router.state.location.search).toEqual({ line: "e1-D2" });
    expect(lineButton(/^BP 90\/60 mmHg, HR 121/)).toHaveAttribute("aria-current", "true");
    // The draft's own wrong number is marked in the line itself.
    expect(lineButton(/^BP 90\/60 mmHg, HR 121/).querySelector(".num-bad")).toHaveTextContent(
      "121",
    );

    const card = within(screen.getByRole("complementary", { name: /came from/ }));
    expect(card.getByRole("heading", { name: "Number differs" })).toBeVisible();
    expect(card.getByText("The draft says 121. Your note says 112.")).toBeVisible();
    expect(card.getByText("From your note")).toBeVisible();
  });

  it("opens straight on a line named in the address", async () => {
    await openNote(NOTE_1, { line: "e1-A2" });
    expect(noteText().querySelectorAll("mark.hl")).toHaveLength(0);
    expect(screen.getByText("No words in your note match this line.")).toBeVisible();
    expect(screen.getByRole("heading", { name: "Not in your note" })).toBeVisible();
    expect(noteText()).not.toHaveClass("swipe");
  });

  it("lights up each quote of a line and swipes them in when you pick it", async () => {
    await openNote(NOTE_1);
    await userEvent.click(lineButton(/^Dizziness with low blood pressure/));
    const marks = [...noteText().querySelectorAll<HTMLElement>("mark.hl")];
    expect(marks.map((m) => m.textContent)).toEqual(["c/o hilo since 2am", "BP 90/60"]);
    expect(marks.map((m) => m.style.getPropertyValue("--i"))).toEqual(["0", "1"]);
    expect(noteText()).toHaveClass("swipe");
  });

  it("treats a line id it does not know as nothing selected", async () => {
    await openNote(NOTE_1, { line: "nope" });
    expect(noteText().querySelectorAll("mark.hl")).toHaveLength(0);
    expect(screen.getByText(/Tap a line in the draft/)).toBeVisible();
  });

  it("moves between lines with the arrow keys, Home and End, selecting each", async () => {
    const app = await openNote(NOTE_1);
    const historyBefore = app.router.history.length;
    await userEvent.click(lineButton(/^Dizziness with low blood pressure/));
    await userEvent.keyboard("{ArrowDown}");
    expect(lineButton(/^Reports dizziness/)).toHaveFocus();
    expect(app.router.state.location.search).toEqual({ line: "e1-D1" });
    await userEvent.keyboard("{ArrowDown}");
    expect(lineButton(/^BP 90\/60 mmHg/)).toHaveFocus();
    await userEvent.keyboard("{ArrowUp}");
    expect(lineButton(/^Reports dizziness/)).toHaveFocus();
    await userEvent.keyboard("{End}");
    expect(lineButton(/^Still weak/)).toHaveFocus();
    expect(app.router.state.location.search).toEqual({ line: "e1-R1" });
    await userEvent.keyboard("{ArrowDown}");
    expect(lineButton(/^Still weak/)).toHaveFocus();
    await userEvent.keyboard("{Home}");
    expect(lineButton(/^Dizziness with low blood pressure/)).toHaveFocus();
    // Selecting replaces the address, so the Back button is not buried under every arrow press.
    expect(app.router.history.length).toBe(historyBefore);
  });

  it("keeps every line in the Tab order: Tab goes from one line to the next", async () => {
    await openNote(NOTE_1);
    await userEvent.click(lineButton(/^Dizziness with low blood pressure/));
    await userEvent.tab();
    expect(lineButton(/^Reports dizziness/)).toHaveFocus();
    await userEvent.tab();
    expect(lineButton(/^BP 90\/60 mmHg/)).toHaveFocus();
    await userEvent.tab({ shift: true });
    expect(lineButton(/^Reports dizziness/)).toHaveFocus();
    // Tabbing only moves the focus; the arrow keys are the ones that select.
    expect(lineButton(/^Dizziness/)).toHaveAttribute("aria-current", "true");
  });

  it("makes the answer line a polite live region", async () => {
    await openNote(NOTE_1);
    expect(screen.getByText("3 lines need you before you sign.")).toHaveAttribute(
      "aria-live",
      "polite",
    );
  });

  it("lists only the words the server found in the note, as the nurse wrote them", async () => {
    await openWith(
      (note) => {
        const d1 = linesInOrder(note.draft).find((l) => l.id === "e1-D1");
        if (!d1) throw new Error("no D1");
        d1.source_quotes = [
          { text: "the AI's own string", span: { start: 3, end: 21 } },
          { text: "not anywhere in the note", span: null },
        ];
        return note;
      },
      200,
      { line: "e1-D1" },
    );
    const card = within(await screen.findByRole("complementary", { name: /came from/ }));
    const items = card.getAllByRole("listitem");
    expect(items.map((li) => li.textContent)).toEqual(["c/o hilo since 2am"]);
    expect(card.queryByText(/the AI's own string|not anywhere/)).toBeNull();
    expect(noteText().querySelector("mark.hl")).toHaveTextContent("c/o hilo since 2am");
  });

  it("says no words match when none of a line's quotes has a span", async () => {
    await openWith(
      (note) => {
        const d1 = linesInOrder(note.draft).find((l) => l.id === "e1-D1");
        if (!d1) throw new Error("no D1");
        d1.source_quotes = [{ text: "not anywhere in the note", span: null }];
        return note;
      },
      200,
      { line: "e1-D1" },
    );
    const card = within(await screen.findByRole("complementary", { name: /came from/ }));
    expect(card.getByText("No words in your note match this line.")).toBeVisible();
    expect(card.queryByRole("listitem")).toBeNull();
  });

  it("says nothing is missing when the checklist is empty", async () => {
    await openWith((note) => ({ ...note, checklist: [] }));
    expect(await screen.findByText("Nothing is missing.")).toBeVisible();
    // An empty list would draw a stray rule under the sentence.
    expect(document.querySelector(".check-items")).toBeNull();
  });

  it("Sign note jumps to the next line that needs you and says so, then goes on round", async () => {
    const app = await openNote(NOTE_1);
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("");
    expect(screen.getByRole("button", { name: "Sign note" })).not.toHaveAttribute("disabled");

    const sign = () => userEvent.click(screen.getByRole("button", { name: "Sign note" }));
    // The words are set on the next frame, after a clear, so a repeat is read out again.
    const said = () =>
      waitFor(() => {
        expect(status).toHaveTextContent("Check this line before you sign.");
      });

    await sign();
    expect(lineButton(/^Dizziness with low/)).toHaveFocus();
    expect(app.router.state.location.search).toEqual({ line: "e1-F" });
    await said();
    expect(screen.getByRole("status")).toBe(status);

    await sign();
    expect(lineButton(/^BP 90\/60 mmHg/)).toHaveFocus();
    await said();
    await sign();
    expect(lineButton(/^Physician notified/)).toHaveFocus();
    await said();
    await sign();
    expect(lineButton(/^Dizziness with low/)).toHaveFocus();
    await said();
  });

  it("opens the signing dialog, and selects no line, when none needs you", async () => {
    const app = await openWith((note) => {
      for (const line of linesInOrder(note.draft)) line.review = "confirmed";
      return note;
    });
    await screen.findByRole("heading", { name: "Your note" });
    expect(screen.getByText("All lines checked. Ready to sign.")).toBeVisible();
    expect(screen.getByText("Every line is checked.")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Sign note" }));
    expect(await screen.findByRole("dialog", { name: "Sign this FDAR note" })).toBeVisible();
    expect(app.router.state.location.search).toEqual({});
  });

  it.each([
    ["signed", "Signed. This note is locked."],
    ["discarded", "Discarded. This draft won't reach the record."],
  ] as const)(
    "says a %s note is not for signing, and has no Sign note button",
    async (status, text) => {
      await openWith((note) => ({ ...note, status }));
      expect(await screen.findByText(text)).toBeVisible();
      expect(screen.queryByRole("button", { name: "Sign note" })).toBeNull();
    },
  );

  describe("on a small screen", () => {
    it("opens the drawer for a line, and Escape closes it and gives the focus back", async () => {
      mockScreen(false);
      const app = await openNote(NOTE_1);
      const trace = screen.getByRole("complementary", { hidden: true, name: /came from/ });
      expect(trace).not.toHaveClass("open");

      await userEvent.click(lineButton(/^Physician notified/));
      expect(trace).toHaveClass("open");
      expect(app.router.state.location.search).toEqual({ line: "e1-A2" });

      // Move the focus into the drawer first, so Escape has to bring it back to the line.
      const close = within(trace).getByRole("button", { name: "Close" });
      act(() => {
        close.focus();
      });
      expect(close).toHaveFocus();
      await userEvent.keyboard("{Escape}");
      expect(trace).not.toHaveClass("open");
      expect(app.router.state.location.search).toEqual({});
      expect(lineButton(/^Physician notified/)).toHaveFocus();
    });

    it("follows the window across 960 px: a selected line opens the drawer when it shrinks", async () => {
      const resize = mockScreen(true);
      await openNote(NOTE_1);
      const trace = screen.getByRole("complementary", { hidden: true, name: /came from/ });
      await userEvent.click(lineButton(/^Still weak/));
      expect(trace).not.toHaveClass("open");
      resize(false);
      expect(trace).toHaveClass("open");
      resize(true);
      expect(trace).not.toHaveClass("open");
    });

    it("closes with the Close button, or by tapping the same line again", async () => {
      mockScreen(false);
      await openNote(NOTE_1);
      const trace = screen.getByRole("complementary", { hidden: true, name: /came from/ });

      await userEvent.click(lineButton(/^Still weak/));
      expect(trace).toHaveClass("open");
      await userEvent.click(within(trace).getByRole("button", { name: "Close" }));
      expect(trace).not.toHaveClass("open");
      expect(lineButton(/^Still weak/)).toHaveFocus();

      await userEvent.click(lineButton(/^Still weak/));
      expect(trace).toHaveClass("open");
      await userEvent.click(lineButton(/^Still weak/));
      expect(trace).not.toHaveClass("open");
      expect(lineButton(/^Still weak/)).toHaveFocus();
    });

    it("keeps the card up when the same line is tapped on a wide screen", async () => {
      mockScreen(true);
      const app = await openNote(NOTE_1);
      await userEvent.click(lineButton(/^Still weak/));
      await userEvent.click(lineButton(/^Still weak/));
      expect(app.router.state.location.search).toEqual({ line: "e1-R1" });
      await userEvent.keyboard("{Escape}");
      expect(app.router.state.location.search).toEqual({ line: "e1-R1" });
    });
  });

  describe("when the note does not load", () => {
    it("says the note is not on the list for a 404", async () => {
      const app = await signIn();
      await goToNote(app, "00000000-0000-4000-8000-0000000000ff");
      expect(
        await screen.findByText("This note is not on your list. Go back and pick one."),
      ).toBeVisible();
    });

    it("shows a plain error, with a way back, for any other failure", async () => {
      await openWith((note) => note, 500);
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "This note did not load. Go back and try again.",
      );
      expect(screen.getByRole("link", { name: "Back to the patients" })).toBeVisible();
    });

    it("keeps the note, the draft and the selected line when a refetch fails", async () => {
      const app = await openNote(NOTE_1, { line: "e1-D2" });
      server.use(http.get("*/api/v1/notes/:id", () => HttpResponse.json({}, { status: 500 })));
      await act(() => app.queryClient.refetchQueries({ queryKey: ["note", NOTE_1] }));
      await waitFor(() => {
        expect(app.queryClient.getQueryState(["note", NOTE_1])?.status).toBe("error");
      });
      expect(screen.queryByRole("alert")).toBeNull();
      expect(screen.getByText("The draft says 121. Your note says 112.")).toBeVisible();
      expect(noteText().querySelector("mark.hl")).toHaveTextContent("BP 90/60 HR 112");
    });

    it("says it is loading while it waits", async () => {
      const app = await signIn();
      server.use(
        http.get("*/api/v1/notes/:id", async ({ params }) => {
          await delay(50);
          return HttpResponse.json(demoNote(String(params["id"])));
        }),
      );
      await goToNote(app, NOTE_1);
      expect(await screen.findByText("Loading the note…")).toBeInTheDocument();
      expect(await screen.findByRole("heading", { name: "Your note" })).toBeVisible();
      expect(screen.queryByText("Loading the note…")).toBeNull();
    });
  });
});
