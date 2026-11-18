import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import type { components } from "../api/schema";
import { Icon, type IconName } from "../components/Icon";
import { Button } from "../components/ui/Button";
import { patientQuery } from "../patients/patients";
import type { Locale } from "../region/words";
import { formatTime } from "../region/format";
import { noteStatus, type NoteStatusKind } from "./draft";
import { draftAgainOutcome, useDraftAgain } from "./draftAgain";
import { draftJobQuery } from "./roughNote";

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
 * it finishes, so the row goes from Drafting to a draft she can open (or to its new failure).
 */
function FollowJob({
  jobId,
  patientId,
  onDone,
}: {
  jobId: string;
  patientId: string;
  onDone: () => void;
}) {
  const queryClient = useQueryClient();
  const job = useQuery(draftJobQuery(jobId));
  const finished = job.data?.status === "succeeded" || job.data?.status === "failed";
  const gone = job.data === undefined && job.isError;
  useEffect(() => {
    if (!finished && !gone) return;
    void queryClient.invalidateQueries({ queryKey: patientQuery(patientId).queryKey });
    onDone();
  }, [finished, gone, patientId, queryClient, onDone]);
  return null;
}

/** This shift's notes so far, newest last, like lines going down a page. */
export function ShiftNotes({
  patientId,
  notes,
  timeZone,
  locale,
  clock,
}: {
  patientId: string;
  notes: components["schemas"]["ShiftNoteOut"][];
  timeZone: string;
  locale: Locale;
  clock: Clock;
}) {
  const again = useDraftAgain(patientId);
  // The jobs this list started (by rough note), until the list shows them.
  const [started, setStarted] = useState<Record<string, string>>({});
  const [problem, setProblem] = useState<{ roughNoteId: string; words: string } | null>(null);

  const tryAgain = (roughNoteId: string) => {
    setProblem(null);
    again.ask(roughNoteId, {
      onSuccess: (job) => {
        setStarted((now) => ({ ...now, [roughNoteId]: job.id }));
      },
      onError: (error) => {
        const outcome = draftAgainOutcome(error);
        if (outcome.kind === "words") setProblem({ roughNoteId, words: outcome.words });
      },
    });
  };

  return (
    <section
      aria-labelledby="shift-notes-heading"
      className="rounded-sheet border border-rule bg-sheet p-4 shadow-(--lift)"
    >
      <h2 id="shift-notes-heading" className="text-18 leading-tight font-bold">
        Notes this shift
      </h2>
      {Object.entries(started).map(([roughNoteId, jobId]) => (
        <FollowJob
          key={jobId}
          jobId={jobId}
          patientId={patientId}
          onDone={() => {
            setStarted((now) =>
              Object.fromEntries(Object.entries(now).filter(([id]) => id !== roughNoteId)),
            );
          }}
        />
      ))}
      {notes.length === 0 ? (
        <p className="mt-2 text-ink-2">
          No notes yet this shift. Write the first one in Your note.
        </p>
      ) : (
        <ul aria-labelledby="shift-notes-heading" className="m-0 mt-2 list-none p-0">
          {notes.map((item) => {
            const status = noteStatus(item);
            const look = LOOK[status.kind];
            const time = formatTime(item.written_at, { timeZone, locale, clock });
            const waiting =
              (again.isPending && again.variables === item.rough_note_id) ||
              // Started, and the list has not caught up yet.
              (started[item.rough_note_id] !== undefined &&
                started[item.rough_note_id] !== item.job.id);
            return (
              <li
                key={item.rough_note_id + item.job.id + item.written_at}
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
                  <Button
                    className="mt-1"
                    disabled={waiting}
                    onClick={() => {
                      tryAgain(item.rough_note_id);
                    }}
                  >
                    Try drafting again
                  </Button>
                ) : null}
                {problem?.roughNoteId === item.rough_note_id ? (
                  <p role="alert" className="mt-1 w-full font-semibold text-stop">
                    {problem.words}
                  </p>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
