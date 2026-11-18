import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useCallback, useEffect, useState } from "react";
import type { components } from "../api/schema";
import { Icon, type IconName } from "../components/Icon";
import { patientQuery } from "../patients/patients";
import type { Locale } from "../region/words";
import { formatTime } from "../region/format";
import { noteStatus, type NoteStatusKind } from "./draft";
import { RowDraftAgain } from "./RowDraftAgain";
import { draftJobQuery, isRefused } from "./roughNote";

type Clock = components["schemas"]["FacilityProfile"]["clock"];

const LOOK: Record<NoteStatusKind, { icon: IconName; tone: string }> = {
  drafting: { icon: "box", tone: "text-ink-2" },
  ready: { icon: "pen", tone: "text-pen" },
  signed: { icon: "you", tone: "text-ok" },
  discarded: { icon: "removed", tone: "text-ink-2" },
  failed: { icon: "flag", tone: "text-stop" },
};

/**
 * Follows a draft job that "Try drafting again" started from the list, and refreshes the list when
 * it finishes, so the row goes from Drafting to a draft she can open (or to its new failure). A
 * poll that fails is asked again on the usual schedule; only an answer that says the job is not
 * there stops it (the list then shows where the note really stands).
 */
function FollowJob({
  jobId,
  patientId,
  roughNoteId,
  onDone,
}: {
  jobId: string;
  roughNoteId: string;
  patientId: string;
  /** Must be the same function on every draw (wrap it in `useCallback`). */
  onDone: (roughNoteId: string, status: "succeeded" | "failed" | "gone") => void;
}) {
  const queryClient = useQueryClient();
  const job = useQuery(draftJobQuery(jobId));
  const ended =
    job.data?.status === "succeeded" || job.data?.status === "failed"
      ? job.data.status
      : job.data === undefined && isRefused(job.error)
        ? "gone"
        : null;
  useEffect(() => {
    if (ended === null) return;
    void queryClient.invalidateQueries({ queryKey: patientQuery(patientId).queryKey });
    onDone(roughNoteId, ended);
  }, [ended, patientId, roughNoteId, queryClient, onDone]);
  return null;
}

const ENDED_WORDS = {
  succeeded: "The draft is ready.",
  failed: "The draft failed again.",
  gone: "",
} as const;

/** This shift's notes so far, newest last, like lines going down a page. */
export function ShiftNotes({
  patientId,
  notes,
  listReadAt,
  timeZone,
  locale,
  clock,
}: {
  patientId: string;
  notes: components["schemas"]["ShiftNoteOut"][];
  /** When the list was last read (the patient query's `dataUpdatedAt`). */
  listReadAt: number;
  timeZone: string;
  locale: Locale;
  clock: Clock;
}) {
  // The jobs this list started (by rough note), until the list shows them.
  const [started, setStarted] = useState<Record<string, string>>({});
  // Said aloud (not a status region: the page has one, and a screen reader hears this one too).
  const [announced, setAnnounced] = useState("");
  const jobEnded = useCallback((roughNoteId: string, status: keyof typeof ENDED_WORDS) => {
    setAnnounced(ENDED_WORDS[status]);
    setStarted((now) =>
      Object.fromEntries(Object.entries(now).filter(([id]) => id !== roughNoteId)),
    );
  }, []);

  return (
    <section
      aria-labelledby="shift-notes-heading"
      className="rounded-sheet border border-rule bg-sheet p-4 shadow-(--lift)"
    >
      <h2 id="shift-notes-heading" className="text-18 leading-tight font-bold">
        Notes this shift
      </h2>
      <p aria-live="polite" className="sr-only">
        {announced}
      </p>
      {Object.entries(started).map(([roughNoteId, jobId]) => (
        <FollowJob
          key={jobId}
          jobId={jobId}
          roughNoteId={roughNoteId}
          patientId={patientId}
          onDone={jobEnded}
        />
      ))}
      {notes.length === 0 ? (
        <p className="mt-2 text-ink-2">
          No notes yet this shift. Write the first one in Your note.
        </p>
      ) : (
        <ul aria-labelledby="shift-notes-heading" className="m-0 mt-2 list-none p-0">
          {notes.map((item) => {
            // Started here, and the list has not caught up yet: it is drafting.
            const restarted =
              started[item.rough_note_id] !== undefined &&
              started[item.rough_note_id] !== item.job.id;
            const status = restarted
              ? { kind: "drafting" as const, label: "Drafting", noteId: null }
              : noteStatus(item);
            const look = LOOK[status.kind];
            const time = formatTime(item.written_at, { timeZone, locale, clock });
            const rowId = `note-row-${item.rough_note_id}`;
            return (
              <li
                key={item.rough_note_id + item.written_at}
                id={rowId}
                tabIndex={-1}
                className="flex flex-wrap items-baseline gap-x-3 border-b border-ruled py-2 last:border-b-0"
              >
                <span className="min-w-16 font-semibold">{time}</span>
                <span className={`inline-flex items-center gap-2 font-semibold ${look.tone}`}>
                  <Icon name={look.icon} />
                  {(status.kind === "ready" || status.kind === "signed") && status.noteId ? (
                    <Link
                      to="/notes/$noteId"
                      params={{ noteId: status.noteId }}
                      className="inline-flex min-h-11 items-center text-pen underline underline-offset-4"
                    >
                      {status.label}
                    </Link>
                  ) : (
                    <span>{status.label}</span>
                  )}
                </span>
                {status.kind === "failed" && item.job.retryable ? (
                  <RowDraftAgain
                    key={item.job.id}
                    patientId={patientId}
                    roughNoteId={item.rough_note_id}
                    listReadAt={listReadAt}
                    onTap={() => document.getElementById(rowId)?.focus()}
                    onStarted={(job) => {
                      setAnnounced("Drafting again.");
                      setStarted((now) => ({ ...now, [item.rough_note_id]: job.id }));
                    }}
                  />
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
