import { useNavigate } from "@tanstack/react-router";
import { useEffect, useEffectEvent, useRef, useState } from "react";
import type { components } from "../api/schema";
import { BedTab } from "../components/BedTab";
import { SyntheticTag } from "../components/SyntheticTag";
import { useMediaQuery } from "../lib/useMediaQuery";
import { formatDayMonth, formatShiftRange, formatTime } from "../region/format";
import { words, type Locale } from "../region/words";
import { Checklist } from "./Checklist";
import { DraftForm, StatusKey } from "./DraftForm";
import { Segments } from "./Segments";
import { TraceCard } from "./TraceCard";
import "./trace.css";
import {
  answerText,
  linesInOrder,
  needsReview,
  nextLineNeedingReview,
  noteMarks,
  spansFor,
} from "./trace";

type Note = components["schemas"]["NoteOut"];
type Clock = components["schemas"]["FacilityProfile"]["clock"];

const WIDE = "(min-width: 960px)";

/** The trace view: the nurse's note, the AI's draft beside it, and the words each line came from. */
export function TraceView({
  note,
  locale,
  clock,
  selectedId,
}: {
  note: Note;
  locale: Locale;
  clock: Clock;
  /** The `?line=` of the address, if it names a line of this draft. */
  selectedId: string | undefined;
}) {
  const navigate = useNavigate({ from: "/notes/$noteId" });
  const wide = useMediaQuery(WIDE);
  const w = words(locale);
  const { rough_note: rough, patient, draft } = note;
  const lines = linesInOrder(draft);
  const selected = lines.find((l) => l.id === selectedId);
  const open = !wide && selected !== undefined;

  const lineButtons = useRef(new Map<string, HTMLButtonElement>());
  const noteText = useRef<HTMLParagraphElement>(null);
  // The line the nurse picked herself: only that selection swipes (a reload with ?line= just shows it).
  const [swipeId, setSwipeId] = useState<string | undefined>(undefined);
  // How many times "Sign note" has said its line. The text alternates a trailing space, so the
  // live region changes (and is read out) every time, even for the same words.
  const [announced, setAnnounced] = useState(0);
  const announcement =
    announced === 0 ? "" : `Check this line before you sign.${announced % 2 === 0 ? " " : ""}`;

  const setLine = (id: string | undefined) => {
    void navigate({ search: id === undefined ? {} : { line: id }, replace: true });
  };
  const focusLine = (id: string) => {
    lineButtons.current.get(id)?.focus();
  };
  const pick = (id: string) => {
    setSwipeId(id);
    setLine(id);
    focusLine(id);
  };
  const close = () => {
    const id = selected?.id;
    setLine(undefined);
    if (id !== undefined) focusLine(id);
  };

  const onPick = (id: string) => {
    if (!wide && selectedId === id) close();
    else pick(id);
  };
  const onArrow = (id: string, key: string) => {
    const at = lines.findIndex((l) => l.id === id);
    const to =
      key === "ArrowDown"
        ? Math.min(at + 1, lines.length - 1)
        : key === "ArrowUp"
          ? Math.max(at - 1, 0)
          : key === "Home"
            ? 0
            : lines.length - 1;
    const target = lines[to];
    if (target) pick(target.id);
  };

  const onSign = () => {
    const next = nextLineNeedingReview(draft, selected?.id);
    if (!next) return; // W5: nothing is left to check, so this will open the signing dialog.
    pick(next.id);
    setAnnounced((count) => count + 1);
  };

  // Escape closes the drawer (small screens only: on a wide one the card is always there).
  const onEscape = useEffectEvent((event: KeyboardEvent) => {
    if (event.key === "Escape") close();
  });
  useEffect(() => {
    if (!open) return;
    document.addEventListener("keydown", onEscape);
    return () => {
      document.removeEventListener("keydown", onEscape);
    };
  }, [open]);

  // On a wide screen the note is sticky; bring the first lit-up words into view.
  useEffect(() => {
    if (selectedId === undefined || !wide) return;
    const first = noteText.current?.querySelector("mark.hl");
    // jsdom has no scrolling.
    if (first && typeof first.scrollIntoView === "function")
      first.scrollIntoView({ block: "nearest" });
  }, [selectedId, wide]);

  const timeZone = rough.shift.timezone;
  const typedAt = formatTime(rough.written_at, { timeZone, locale, clock });
  const left = lines.filter(needsReview).length;
  const ready = note.status === "signed" || (note.status === "draft" && left === 0);
  const handlers = {
    selectedId: selected?.id,
    tabStopId: selected?.id ?? lines[0]?.id,
    register: (id: string, element: HTMLButtonElement | null) => {
      if (element) lineButtons.current.set(id, element);
      else lineButtons.current.delete(id);
    },
    onPick,
    onArrow,
  };

  return (
    <div className="trace-view">
      <div className="note-head">
        <BedTab large className="bed-tab" word={w.bed} label={patient.bed_label} />
        <h1 className="who-name">
          {patient.display_name} <SyntheticTag />
        </h1>
        <p className="who-meta">
          {`${String(patient.age)} ${patient.sex}, ${patient.ward}. ${w.noteFormat(rough.note_format)} note for the ${rough.shift.label} shift, ${formatShiftRange(rough.shift, { locale, clock })}.`}
        </p>
      </div>

      <div className="trace-layout">
        <section className="pane-note" aria-labelledby="note-h">
          <div>
            <div className="pane-head">
              <h2 id="note-h">Your note</h2>
              <p>{`Typed at ${typedAt}. The AI never changes it.`}</p>
            </div>
            <div className="note-sheet">
              <p
                // Keyed by the line so the swipe starts again each time a new line is picked.
                key={selected?.id ?? "none"}
                ref={noteText}
                className={
                  swipeId !== undefined && swipeId === selected?.id
                    ? "note-text swipe"
                    : "note-text"
                }
              >
                <Segments segments={spansFor(rough.text, selected ? noteMarks(selected) : [])} />
              </p>
            </div>
          </div>
          <TraceCard line={selected} open={open} onClose={close} />
        </section>

        <section className="pane-draft" aria-labelledby="draft-h">
          <div className="pane-head">
            <h2 id="draft-h">{`${w.noteFormat(rough.note_format)} draft`}</h2>
            <p>Written by AI, checked by code. Tap a line to see the words it came from.</p>
          </div>
          <p className={ready ? "answer is-ready" : "answer"}>{answerText(draft, note.status)}</p>
          <StatusKey draft={draft} />
          <DraftForm
            draft={draft}
            time={{
              date: formatDayMonth(rough.written_at, { timeZone, locale }),
              clock: typedAt,
            }}
            handlers={handlers}
          />
          <Checklist items={note.checklist} noteText={rough.text} />
          {note.status === "draft" ? (
            <div className="signbar">
              <button type="button" className="btn btn-primary" onClick={onSign}>
                Sign note
              </button>
              <span className="signbar-msg">
                {left > 0 ? (
                  <>
                    <b>{`${String(left)} ${left === 1 ? "line" : "lines"}`}</b> to check first
                  </>
                ) : (
                  "Every line is checked."
                )}
              </span>
            </div>
          ) : null}
        </section>
      </div>

      {/* Always on the page, empty until something is said: a screen reader announces a change, not a new node. */}
      <p role="status" className="sr-only">
        {announcement}
      </p>
    </div>
  );
}
