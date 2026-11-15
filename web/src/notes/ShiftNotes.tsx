import { Link } from "@tanstack/react-router";
import type { components } from "../api/schema";
import { Icon, type IconName } from "../components/Icon";
import type { Locale } from "../region/words";
import { formatTime } from "../region/format";
import { noteStatus, type NoteStatusKind } from "./draft";

type Clock = components["schemas"]["FacilityProfile"]["clock"];

const LOOK: Record<NoteStatusKind, { icon: IconName; tone: string }> = {
  drafting: { icon: "box", tone: "text-ink-2" },
  ready: { icon: "pen", tone: "text-pen" },
  signed: { icon: "you", tone: "text-ok" },
  discarded: { icon: "removed", tone: "text-ink-2" },
  failed: { icon: "flag", tone: "text-stop" },
};

/** This shift's notes so far, newest last, like lines going down a page. */
export function ShiftNotes({
  notes,
  timeZone,
  locale,
  clock,
}: {
  notes: components["schemas"]["ShiftNoteOut"][];
  timeZone: string;
  locale: Locale;
  clock: Clock;
}) {
  return (
    <section
      aria-labelledby="shift-notes-heading"
      className="rounded-sheet border border-rule bg-sheet p-4 shadow-(--lift)"
    >
      <h2 id="shift-notes-heading" className="text-18 leading-tight font-bold">
        Notes this shift
      </h2>
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
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
