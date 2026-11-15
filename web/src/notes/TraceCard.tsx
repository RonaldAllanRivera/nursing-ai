import { Icon } from "../components/Icon";
import { LineActions } from "./LineActions";
import { Segments } from "./Segments";
import { quoteSegments, reasonFor, shownStatus, type DraftLine } from "./trace";

/**
 * "Where the selected line came from". Under the note on a wide screen; on a small one a bottom
 * drawer (not modal: the draft stays usable behind it). Close, Escape or tapping the line again
 * closes it.
 */
export function TraceCard({
  line,
  noteText,
  open,
  onClose,
  actions,
}: {
  line: DraftLine | undefined;
  /** The nurse's note: the quotes are shown as her own words at their spans. */
  noteText: string;
  /** Small screens only: whether the drawer is up. */
  open: boolean;
  onClose: () => void;
  /** What she can do to the line: only on a draft (a signed or discarded note has none). */
  actions?:
    | {
        noteId: string;
        announce: (message: string) => void;
        onSettled: (id: string) => void;
      }
    | undefined;
}) {
  const shown = line ? shownStatus(line) : undefined;
  const quotes = line ? quoteSegments(line, noteText) : [];
  return (
    <aside
      id="trace"
      aria-label="Where the selected line came from"
      className={open ? "trace open" : "trace"}
    >
      <div className="drawer-bar">
        <span>Where this line came from</span>
        <button type="button" className="btn" onClick={onClose}>
          <Icon name="close" />
          Close
        </button>
      </div>
      {line && shown ? (
        <div>
          <p className="trace-line">
            <q>{line.text}</q>
          </p>
          <h2 className={`trace-status tone-${shown.tone}`}>
            <Icon name={shown.icon} />
            {shown.label}
          </h2>
          <p className="trace-reason">{reasonFor(line)}</p>
          <h3>From your note</h3>
          {quotes.length > 0 ? (
            <ul className="quotes">
              {quotes.map(({ index, segments }) => (
                <li key={index}>
                  <Segments segments={segments} />
                </li>
              ))}
            </ul>
          ) : (
            <p className="no-quote">
              <Icon name="flag" />
              No words in your note match this line.
            </p>
          )}
          {actions ? <LineActions key={line.id} line={line} {...actions} /> : null}
        </div>
      ) : (
        <p className="trace-empty">
          Tap a line in the draft. The words it came from light up in your note,{" "}
          <mark className="hl">like this</mark>.
        </p>
      )}
    </aside>
  );
}
