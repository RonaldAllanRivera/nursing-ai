import { useEffect, useRef, useState } from "react";
import { Icon } from "../components/Icon";
import { actionsFor, type DraftLine, type LineAction } from "./trace";
import { WriteProblem } from "./WriteProblem";
import { useActOnLine, type LineBody } from "./writes";

const MAX_LINE = 500;

/** "112", "112 and 37.8", "112, 37.8 and 5". */
function listed(items: string[]): string {
  const last = items.at(-1) ?? "";
  return items.length < 2 ? last : `${items.slice(0, -1).join(", ")} and ${last}`;
}

function label(action: LineAction): string {
  switch (action.kind) {
    case "confirm":
      return "Wording is right";
    case "use":
      return `Use ${action.replacement} from your note`;
    case "useAll":
      return "Use the numbers from your note";
    case "remove":
      return "Remove line";
    case "edit":
      return "Edit line";
    case "undo":
      return "Undo";
    case "putBack":
      return "Put line back";
  }
}

const FIRM: LineAction["kind"][] = ["confirm", "use", "useAll", "remove", "putBack"];

function bodyOf(action: LineAction): LineBody | undefined {
  switch (action.kind) {
    case "confirm":
      return { action: "confirm" };
    case "use":
    case "useAll":
      return { action: "edit", text: action.text };
    case "remove":
      return { action: "remove" };
    case "undo":
    case "putBack":
      return { action: "restore" };
    case "edit":
      return undefined;
  }
}

function saidFor(action: LineAction): string {
  switch (action.kind) {
    case "confirm":
      return "Wording confirmed.";
    case "use":
      return `Changed to ${action.replacement}.`;
    case "useAll":
      return `Changed to ${listed(action.replacements)}.`;
    case "remove":
      return "Line removed.";
    case "undo":
    case "putBack":
      return "Line put back as the AI wrote it.";
    case "edit":
      return "Line saved.";
  }
}

/**
 * What the nurse can do to the selected line, in the trace card: the buttons for its state, or
 * the edit box. Keyed by the line in the card, so picking another line starts afresh.
 */
export function LineActions({
  line,
  noteId,
  announce,
  onSettled,
}: {
  line: DraftLine;
  noteId: string;
  announce: (message: string) => void;
  /** A change went through: the focus goes back to the line in the draft. */
  onSettled: (lineId: string) => void;
}) {
  const act = useActOnLine(noteId);
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(line.text);
  const [invalid, setInvalid] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const field = useRef<HTMLTextAreaElement>(null);
  const busy = act.isPending;

  // She asked to edit: the box is where she goes next.
  useEffect(() => {
    if (editing) field.current?.focus();
  }, [editing]);

  const send = (body: LineBody, said: string, after: () => void) => {
    if (busy) return;
    act.mutate(
      { lineId: line.id, body },
      {
        onSuccess: () => {
          announce(said);
          after();
        },
      },
    );
  };
  const focusEditButton = () => {
    requestAnimationFrame(() => {
      box.current?.querySelector<HTMLElement>("[data-act='edit']")?.focus();
    });
  };

  const save = () => {
    if (busy) return;
    const trimmed = text.trim();
    const length = Array.from(trimmed).length;
    if (length === 0) {
      setInvalid("A line needs 1 to 500 characters. Write something, or cancel.");
      return;
    }
    if (length > MAX_LINE) {
      setInvalid("A line can be 500 characters at most. Shorten it, or cancel.");
      return;
    }
    setInvalid(null);
    send({ action: "edit", text: trimmed }, "Line saved.", () => {
      setEditing(false);
      onSettled(line.id);
    });
  };

  const problem = act.isError ? (
    <WriteProblem
      error={act.error}
      withText={editing}
      noteId={noteId}
      onReloaded={() => {
        act.reset();
      }}
    />
  ) : null;

  if (editing) {
    return (
      <div className="edit-box" ref={box} aria-busy={busy || undefined}>
        <label htmlFor="edit-text">Edit line</label>
        <textarea
          id="edit-text"
          rows={4}
          value={text}
          ref={field}
          aria-invalid={invalid !== null || undefined}
          aria-describedby={invalid === null ? undefined : "edit-invalid"}
          onChange={(event) => {
            setText(event.target.value);
            setInvalid(null);
          }}
        />
        {invalid === null ? null : (
          <p id="edit-invalid" role="alert" className="write-problem">
            <Icon name="flag" />
            <span>{invalid}</span>
          </p>
        )}
        {problem}
        <div className="actions edit-actions">
          <button
            type="button"
            className="btn btn-firm"
            aria-disabled={busy || undefined}
            onClick={save}
          >
            {busy ? "Saving…" : "Save line"}
          </button>
          {/* While the line saves, the way out waits: "Saving…" is the reason. */}
          <button
            type="button"
            className="btn"
            aria-disabled={busy || undefined}
            onClick={() => {
              if (busy) return;
              act.reset();
              setInvalid(null);
              setEditing(false);
              setText(line.text);
              focusEditButton();
            }}
          >
            Cancel
          </button>
        </div>
      </div>
    );
  }

  return (
    <div ref={box} aria-busy={busy || undefined}>
      <div className="actions">
        {actionsFor(line).map((action) => (
          <button
            key={action.kind === "use" ? `use-${action.replacement}` : action.kind}
            type="button"
            data-act={action.kind}
            className={FIRM.includes(action.kind) ? "btn btn-firm" : "btn"}
            aria-disabled={busy || undefined}
            onClick={() => {
              if (busy) return;
              const body = bodyOf(action);
              if (!body) {
                setText(line.text);
                setEditing(true);
                return;
              }
              send(body, saidFor(action), () => {
                onSettled(line.id);
              });
            }}
          >
            {action.kind === "edit" ? <Icon name="pen" /> : null}
            {action.kind === "confirm" ? <Icon name="check" /> : null}
            {action.kind === "remove" ? <Icon name="removed" /> : null}
            {label(action)}
          </button>
        ))}
      </div>
      {problem}
      {busy ? <span className="sr-only">Saving…</span> : null}
    </div>
  );
}
