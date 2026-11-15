import type { CSSProperties, ReactNode } from "react";
import type { Part, Segment } from "./trace";

function Parts({ parts }: { parts: Part[] }): ReactNode {
  return parts.map((part, i) =>
    part.bad ? (
      <span key={i} className="num-bad">
        {part.text}
      </span>
    ) : (
      part.text
    ),
  );
}

/** Text cut by `spansFor`: a `<mark class="hl">` for each highlight, a `num-bad` span for a differing number. Plain React nodes, no HTML strings. */
export function Segments({ segments }: { segments: Segment[] }) {
  return segments.map((segment, i) =>
    segment.highlight === null ? (
      <Parts key={i} parts={segment.parts} />
    ) : (
      // --i is the quote's index: the swipe starts 140 ms later for each one.
      <mark key={i} className="hl" style={{ "--i": segment.highlight } as CSSProperties}>
        <Parts parts={segment.parts} />
      </mark>
    ),
  );
}
