import { useNavigate } from "@tanstack/react-router";
import { useEffect, useEffectEvent, useRef, useState } from "react";
import type { MouseEvent } from "react";
import type { components } from "../api/schema";
import { BedTab } from "../components/BedTab";
import { Icon } from "../components/Icon";
import { SyntheticTag } from "../components/SyntheticTag";
import { useMediaQuery } from "../lib/useMediaQuery";
import { formatDayMonth, formatShiftRange, formatTime } from "../region/format";
import { words, type Locale } from "../region/words";
import { Checklist } from "./Checklist";
import { DraftForm, StatusKey } from "./DraftForm";
import { SignDialog, DiscardDialog } from "./NoteDialogs";
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
  withoutRemoved,
} from "./trace";

type Note = components["schemas"]["NoteOut"];
type Clock = components["schemas"]["FacilityProfile"]["clock"];

const WIDE = "(min-width: 960px)";

/** The trace view: the nurse's note, the AI's draft beside it, and the words each line came from. */
export function TraceView({
  note,
  locale,
  clock,
  facilityZone,
  me,
  selectedId,
}: {
  note: Note;
  locale: Locale;
  clock: Clock;
  /** The facility's zone: the time a note was signed is shown in it. */
  facilityZone: string;
  /** Who is signed in: who signs, and whether a signature is hers. */
  me: { userId: string; name: string };
  /** The `?line=` of the address, if it names a line of this draft. */
  selectedId: string | undefined;
}) {
  const navigate = useNavigate({ from: "/notes/$noteId" });
  const wide = useMediaQuery(WIDE);
  const w = words(locale);
  const { rough_note: rough, patient, draft } = note;
  // A signed note is the record: the lines the nurse removed are not in it.
  const shownDraft = note.status === "signed" ? withoutRemoved(draft) : draft;
  const lines = linesInOrder(shownDraft);
  const [root, setRoot] = useState<HTMLDivElement | null>(null);
  const [signing, setSigning] = useState(false);
  const [discarding, setDiscarding] = useState(false);
  // Where the focus goes when a dialog closes, when its opener is gone or something else needs her.
  const afterDialog = useRef<(() => void) | null>(null);
  const opener = useRef<HTMLElement | null>(null);
  const lock = useRef<HTMLDivElement>(null);
  const answerLine = useRef<HTMLParagraphElement>(null);
  const selected = lines.find((l) => l.id === selectedId);
  const open = !wide && selected !== undefined;

  const lineButtons = useRef(new Map<string, HTMLButtonElement>());
  const noteText = useRef<HTMLParagraphElement>(null);
  // The line the nurse picked herself: only that selection swipes (a reload with ?line= just shows it).
  const [swipeId, setSwipeId] = useState<string | undefined>(undefined);
  const [announcement, setAnnouncement] = useState("");
  // Clear, then set on the next frame (the mockup's way): the region changes each time, so the
  // same words are read out again.
  const announce = (message: string) => {
    setAnnouncement("");
    requestAnimationFrame(() => {
      setAnnouncement(message);
    });
  };

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

  const onSign = (event: MouseEvent<HTMLButtonElement>) => {
    const next = nextLineNeedingReview(draft, selected?.id);
    if (!next) {
      opener.current = event.currentTarget;
      setSigning(true);
      return;
    }
    pick(next.id);
    announce("Check this line before you sign.");
  };
  // Radix only gives the focus back to a Dialog.Trigger, and these dialogs are opened by buttons
  // that stay in the page: so the opener is kept here, and a dialog that ended it sets `afterDialog`.
  const onCloseAutoFocus = (event: Event) => {
    event.preventDefault();
    const go = afterDialog.current ?? (() => opener.current?.focus());
    afterDialog.current = null;
    go();
  };
  const dialog = {
    container: root,
    noteId: note.id,
    onCloseAutoFocus,
  };

  // Escape closes the drawer (small screens only: on a wide one the card is always there).
  const onEscape = useEffectEvent((event: KeyboardEvent) => {
    if (event.key !== "Escape" || event.defaultPrevented) return;
    // A dialog took this Escape (it prevents the default), and Escape in the edit box must not
    // close the drawer and lose what she typed.
    if (event.target instanceof Element && event.target.closest("textarea")) return;
    close();
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
  const { signature } = note;
  const signedAt =
    signature === null
      ? ""
      : formatTime(signature.signed_at, { timeZone: facilityZone, locale, clock });
  const ready = note.status === "signed" || (note.status === "draft" && left === 0);
  const handlers = {
    selectedId: selected?.id,
    register: (id: string, element: HTMLButtonElement | null) => {
      if (element) lineButtons.current.set(id, element);
      else lineButtons.current.delete(id);
    },
    onPick,
    onArrow,
  };

  return (
    <div className="trace-view" ref={setRoot}>
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
          <TraceCard
            line={selected}
            noteText={rough.text}
            open={open}
            onClose={close}
            actions={
              note.status === "draft"
                ? { noteId: note.id, announce, onSettled: focusLine }
                : undefined
            }
          />
        </section>

        <section className="pane-draft" aria-labelledby="draft-h">
          <div className="pane-head">
            <h2 id="draft-h">{`${w.noteFormat(rough.note_format)} draft`}</h2>
            <p>Written by AI, checked by code. Tap a line to see the words it came from.</p>
          </div>
          <p
            ref={answerLine}
            tabIndex={-1}
            className={ready ? "answer is-ready" : "answer"}
            aria-live="polite"
          >
            {answerText(draft, note.status)}
          </p>
          <StatusKey draft={shownDraft} />
          <DraftForm
            draft={shownDraft}
            time={{
              date: formatDayMonth(rough.written_at, { timeZone, locale }),
              clock: typedAt,
            }}
            handlers={handlers}
          />
          <Checklist items={note.checklist} noteText={rough.text} />
          {note.status === "draft" ? (
            <div className="discard-row">
              <button
                type="button"
                className="btn"
                onClick={(event) => {
                  opener.current = event.currentTarget;
                  setDiscarding(true);
                }}
              >
                Discard draft
              </button>
            </div>
          ) : null}
          {note.status === "signed" && signature ? (
            <div className="signbar">
              <div className="signed" ref={lock} tabIndex={-1}>
                <Icon name="lock" />
                <div>
                  <b>
                    {signature.signed_by === me.userId
                      ? `Signed by you at ${signedAt}.`
                      : `Signed at ${signedAt}.`}
                  </b>
                  <div className="hash">{`Note hash ${signature.content_hash.slice(0, 12)}`}</div>
                </div>
              </div>
            </div>
          ) : null}
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

      <SignDialog
        {...dialog}
        open={signing}
        onOpenChange={setSigning}
        format={w.noteFormat(rough.note_format)}
        signerName={me.name}
        missing={note.checklist.filter((item) => item.missing).map((item) => item.subject)}
        onSigned={() => {
          // The answer line is live and the focus moves to the lock: no third announcement.
          afterDialog.current = () => lock.current?.focus();
        }}
        onIncomplete={(ids) => {
          const first = ids[0];
          if (first === undefined) return;
          setSwipeId(first);
          setLine(first);
          afterDialog.current = () => {
            focusLine(first);
          };
          announce("Check this line before you sign.");
        }}
      />
      <DiscardDialog
        {...dialog}
        open={discarding}
        onOpenChange={setDiscarding}
        onDiscarded={() => {
          afterDialog.current = () => answerLine.current?.focus();
        }}
      />

      {/* Always on the page, empty until something is said: a screen reader announces a change, not a new node. */}
      <p role="status" className="sr-only">
        {announcement}
      </p>
    </div>
  );
}
