import type { KeyboardEvent } from "react";
import { Icon } from "../components/Icon";
import { cn } from "../lib/cn";
import { Segments } from "./Segments";
import {
  KEY_ORDER,
  lineSegments,
  linesInOrder,
  shownStatus,
  statusLook,
  type Draft,
  type DraftLine,
} from "./trace";

export interface LineHandlers {
  selectedId: string | undefined;
  register: (id: string, element: HTMLButtonElement | null) => void;
  onPick: (id: string) => void;
  onArrow: (id: string, key: string) => void;
}

/** One line of the draft: its words, its status, and a button that shows where it came from. */
function LineButton({
  line,
  isFocus = false,
  handlers,
}: {
  line: DraftLine;
  isFocus?: boolean;
  handlers: LineHandlers;
}) {
  const shown = shownStatus(line);
  const selected = handlers.selectedId === line.id;
  const onKeyDown = (event: KeyboardEvent) => {
    if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
      event.preventDefault();
      handlers.onArrow(line.id, event.key);
    }
  };
  return (
    <button
      type="button"
      ref={(element) => {
        handlers.register(line.id, element);
      }}
      aria-current={selected ? "true" : undefined}
      className={cn(
        "line",
        isFocus && "is-focus",
        line.review === "pending" && line.status === "no_source" && "is-unsourced",
        line.review === "removed" && "is-removed",
      )}
      onClick={() => {
        handlers.onPick(line.id);
      }}
      onKeyDown={onKeyDown}
    >
      <span className="line-text">
        <Segments segments={lineSegments(line)} />
      </span>
      <span className={`status tone-${shown.tone}`}>
        <Icon name={shown.icon} />
        {shown.label}
      </span>
    </button>
  );
}

function Section({
  letter,
  name,
  lines,
  handlers,
}: {
  letter: string;
  name: string;
  lines: DraftLine[];
  handlers: LineHandlers;
}) {
  return (
    <div className="dar">
      <span className="dar-letter" aria-hidden="true">
        {letter}
      </span>
      <ol aria-label={name}>
        {lines.length === 0 ? (
          <li className="dar-empty">Not written — left empty</li>
        ) : (
          lines.map((line) => (
            <li key={line.id}>
              <LineButton line={line} handlers={handlers} />
            </li>
          ))
        )}
      </ol>
    </div>
  );
}

/** How many lines of the draft have each status, in the key's order. Icon, words and colour. */
export function StatusKey({ draft }: { draft: Draft }) {
  const lines = linesInOrder(draft);
  return (
    <ul className="key" aria-label="Line checks in this draft">
      {KEY_ORDER.map((status) => {
        const look = statusLook(status);
        return (
          <li key={status} className={`tone-${look.tone}`}>
            <Icon name={look.icon} />
            <span>
              {look.label} <b>{lines.filter((l) => l.status === status).length}</b>
            </span>
          </li>
        );
      })}
    </ul>
  );
}

/** The form: one row for each entry, with a time cell, the focus, then its D, A and R lines. */
export function DraftForm({
  draft,
  time,
  handlers,
}: {
  draft: Draft;
  /** The date and time of the row's time cell (the note's own). */
  time: { date: string; clock: string };
  handlers: LineHandlers;
}) {
  return (
    <div className="form">
      <div className="form-cols" aria-hidden="true">
        <div>Date and time</div>
        <div>Focus</div>
        <div>Progress notes</div>
      </div>
      {draft.entries.map((entry) => (
        <div className="form-row" key={entry.focus.id}>
          <div className="cell-time">
            {time.date}
            <br />
            {time.clock}
          </div>
          <div className="cell-focus">
            <span className="focus-label">Focus</span>
            <LineButton line={entry.focus} isFocus handlers={handlers} />
          </div>
          <div className="cell-progress">
            <Section letter="D" name="Data" lines={entry.data} handlers={handlers} />
            <Section letter="A" name="Action" lines={entry.action} handlers={handlers} />
            <Section letter="R" name="Response" lines={entry.response} handlers={handlers} />
          </div>
        </div>
      ))}
    </div>
  );
}
