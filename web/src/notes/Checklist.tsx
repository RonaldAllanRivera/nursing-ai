import type { components } from "../api/schema";
import { Icon } from "../components/Icon";
import { wordsAt } from "./trace";

type Item = components["schemas"]["ChecklistItem"];

/** What the chart expects in a note and the note lacks, from the server's rules (no AI). A missing item and a present one differ by icon, words and colour. */
export function Checklist({ items, noteText }: { items: Item[]; noteText: string }) {
  return (
    <section className="checklist" aria-labelledby="check-h">
      <h2 id="check-h">Missing from this note</h2>
      <p>The app checks your note against the patient's chart. No AI is used for this list.</p>
      {items.length === 0 ? <p className="check-none">Nothing is missing.</p> : null}
      <ul className="check-items">
        {items.map((item) => (
          <li key={`${item.rule}-${item.subject}`}>
            <Icon
              name={item.missing ? "box" : "boxcheck"}
              className={item.missing ? "tone-review" : "tone-ok"}
            />
            <div>
              <b>{item.subject}</b>
              <span>
                {item.missing
                  ? "Not in your note."
                  : item.note_span
                    ? `In your note: “${wordsAt(noteText, item.note_span)}”`
                    : "In your note."}
              </span>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
