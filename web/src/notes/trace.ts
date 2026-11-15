import type { components } from "../api/schema";

export type DraftLine = components["schemas"]["DraftLine"];
export type Draft = components["schemas"]["FdarDraft"];
type NoteStatus = components["schemas"]["NoteStatus"];
type LineStatus = DraftLine["status"];

// ---------------------------------------------------------------------------------------------
// Spans: the server's [start, end) in code points, turned into pieces for React to render.

/** A highlight carries its quote's index (the swipe is staggered by it); `bad` is a differing number. */
export type Mark =
  | { kind: "highlight"; start: number; end: number; index: number }
  | { kind: "bad"; start: number; end: number };

export interface Part {
  text: string;
  bad: boolean;
}

/** `highlight: null` is a plain run; otherwise one `<mark>` holding its parts, `num-bad` ones nested. */
export interface Segment {
  highlight: number | null;
  parts: Part[];
}

interface Range {
  start: number;
  end: number;
}

function clamp(mark: Range, length: number): Range | null {
  const start = Math.max(0, Math.min(mark.start, length));
  const end = Math.max(0, Math.min(mark.end, length));
  return end > start ? { start, end } : null;
}

/** Highlights that overlap or touch become one; the merged mark keeps the lowest quote index. */
function mergeHighlights(ranges: (Range & { index: number })[]) {
  const sorted = [...ranges].sort((a, b) => a.start - b.start || a.end - b.end);
  const merged: (Range & { index: number })[] = [];
  for (const range of sorted) {
    const last = merged.at(-1);
    if (last && range.start <= last.end) {
      last.end = Math.max(last.end, range.end);
      last.index = Math.min(last.index, range.index);
    } else {
      merged.push({ ...range });
    }
  }
  return merged;
}

/**
 * Cuts `text` into runs by the marks. Offsets count code points, so the text is split with
 * `Array.from` (never `text.slice`: an emoji is two UTF-16 units but one code point).
 */
export function spansFor(text: string, marks: Mark[]): Segment[] {
  const chars = Array.from(text);
  const length = chars.length;

  const highlights: (Range & { index: number })[] = [];
  const bads: Range[] = [];
  for (const mark of marks) {
    const range = clamp(mark, length);
    if (!range) continue;
    if (mark.kind === "highlight") highlights.push({ ...range, index: mark.index });
    else bads.push(range);
  }
  const merged = mergeHighlights(highlights);

  // Every place a run can change: the ends of a mark, and the ends of the text.
  const cuts = new Set<number>([0, length]);
  for (const range of [...merged, ...bads]) {
    cuts.add(range.start);
    cuts.add(range.end);
  }
  const points = [...cuts].sort((a, b) => a - b);

  const segments: Segment[] = [];
  let currentMark: (typeof merged)[number] | null | undefined;
  for (let i = 0; i + 1 < points.length; i++) {
    const from = points[i] ?? 0;
    const to = points[i + 1] ?? length;
    const mark = merged.find((m) => m.start <= from && to <= m.end) ?? null;
    const bad = bads.some((b) => b.start <= from && to <= b.end);
    const piece = chars.slice(from, to).join("");

    const last = segments.at(-1);
    if (last && mark === currentMark) {
      const lastPart = last.parts.at(-1);
      if (lastPart?.bad === bad) lastPart.text += piece;
      else last.parts.push({ text: piece, bad });
    } else {
      segments.push({ highlight: mark?.index ?? null, parts: [{ text: piece, bad }] });
      currentMark = mark;
    }
  }
  return segments;
}

interface Span {
  start: number;
  end: number;
}

/** The words at a span of the nurse's text (code points, so an emoji before it can't shift it). */
export function wordsAt(text: string, span: Span): string {
  return Array.from(text).slice(span.start, span.end).join("");
}

/** The text with the code points of `span` replaced (an emoji is one code point, so it can't shift the span). */
export function replaceAtSpan(text: string, span: Span, replacement: string): string {
  const chars = Array.from(text);
  const start = Math.max(0, Math.min(span.start, chars.length));
  const end = Math.max(start, Math.min(span.end, chars.length));
  return [...chars.slice(0, start), replacement, ...chars.slice(end)].join("");
}

/**
 * The differing number is marked while the line is pending, or while it is edited and the re-check
 * still found a difference (an edit that fixed one of two numbers must not hide the other). It is
 * not marked once she confirmed or removed the line, or the code no longer finds a difference.
 */
function showsDifference(line: DraftLine): boolean {
  return (
    line.status === "number_mismatch" && (line.review === "pending" || line.review === "edited")
  );
}

/** What a selected line lights up in the nurse's note: its quotes, and the number that differs. */
export function noteMarks(line: DraftLine): Mark[] {
  if (line.review === "removed") return [];
  const marks: Mark[] = [];
  line.source_quotes.forEach((quote, index) => {
    if (quote.span) marks.push({ kind: "highlight", ...quote.span, index });
  });
  if (showsDifference(line)) {
    for (const mismatch of line.number_mismatches) {
      if (mismatch.note_span) marks.push({ kind: "bad", ...mismatch.note_span });
    }
  }
  return marks;
}

/** The line's own text, with the number the draft got wrong marked. */
export function lineSegments(line: DraftLine): Segment[] {
  const marks: Mark[] = showsDifference(line)
    ? line.number_mismatches.map((m) => ({ kind: "bad", ...m.draft_span }))
    : [];
  return spansFor(line.text, marks);
}

/**
 * The quotes the trace card lists under "From your note": only those the server found in the
 * note (a span), each shown as the nurse's own words at that span (never the AI's quote string),
 * with the note's differing number marked inside. A quote with no span isn't in the note.
 */
export function quoteSegments(
  line: DraftLine,
  noteText: string,
): { index: number; segments: Segment[] }[] {
  const found: { index: number; segments: Segment[] }[] = [];
  line.source_quotes.forEach((quote, index) => {
    const at = quote.span;
    if (!at) return;
    const words = wordsAt(noteText, at);
    const marks: Mark[] = [{ kind: "highlight", start: 0, end: Array.from(words).length, index }];
    if (showsDifference(line)) {
      for (const { note_span: bad } of line.number_mismatches) {
        if (bad && at.start <= bad.start && bad.end <= at.end) {
          marks.push({ kind: "bad", start: bad.start - at.start, end: bad.end - at.start });
        }
      }
    }
    found.push({ index, segments: spansFor(words, marks) });
  });
  return found;
}

// ---------------------------------------------------------------------------------------------
// Status, review and the answer line.

export type Tone = "ok" | "review" | "stop" | "you" | "muted";
export type StatusIcon = "check" | "pen" | "neq" | "flag" | "you" | "removed";

export interface Shown {
  /** Which status this is: the key for counting, or what the nurse did. */
  key: LineStatus | "confirmed" | "edited" | "removed";
  label: string;
  tone: Tone;
  icon: StatusIcon;
}

const BY_STATUS: Record<LineStatus, Shown> = {
  source_found: { key: "source_found", label: "Source found", tone: "ok", icon: "check" },
  summary: { key: "summary", label: "AI wording — check", tone: "review", icon: "pen" },
  number_mismatch: { key: "number_mismatch", label: "Number differs", tone: "stop", icon: "neq" },
  no_source: { key: "no_source", label: "Not in your note", tone: "stop", icon: "flag" },
};

/** The four statuses, in the order the key lists them. */
export const KEY_ORDER: LineStatus[] = ["source_found", "summary", "number_mismatch", "no_source"];

export function statusLook(status: LineStatus): Shown {
  return BY_STATUS[status];
}

/** What the nurse sees on a line: what she did to it, or else what the code found. */
export function shownStatus(line: DraftLine): Shown {
  switch (line.review) {
    case "confirmed":
      return { key: "confirmed", label: "Checked by you", tone: "you", icon: "you" };
    // Edited lines are checked again on save, but they stay "Edited by you" whatever that finds.
    case "edited":
      return { key: "edited", label: "Edited by you", tone: "you", icon: "pen" };
    case "removed":
      return { key: "removed", label: "Removed by you", tone: "muted", icon: "removed" };
    case "pending":
      return BY_STATUS[line.status];
  }
}

/** A line needs the nurse while her review is pending and the code did not find its source. */
export function needsReview(line: DraftLine): boolean {
  return line.review === "pending" && line.status !== "source_found";
}

/** Every line in the order the form shows them: each entry's focus, then its D, A and R lines. */
export function linesInOrder(draft: Draft): DraftLine[] {
  return draft.entries.flatMap((entry) => [
    entry.focus,
    ...entry.data,
    ...entry.action,
    ...entry.response,
  ]);
}

/** The first line after `afterId` that needs the nurse, wrapping round (the same line if it is the only one). */
export function nextLineNeedingReview(draft: Draft, afterId?: string): DraftLine | undefined {
  const lines = linesInOrder(draft);
  const at = afterId === undefined ? -1 : lines.findIndex((l) => l.id === afterId);
  for (let step = 1; step <= lines.length; step++) {
    const candidate = lines[(at + step) % lines.length];
    if (candidate && needsReview(candidate)) return candidate;
  }
  return undefined;
}

/** The one sentence that answers "can I sign?". */
export function answerText(draft: Draft, status: NoteStatus): string {
  if (status === "signed") return "Signed. This note is locked.";
  if (status === "discarded") return "Discarded. This draft won't reach the record.";
  const left = linesInOrder(draft).filter(needsReview).length;
  if (left === 0) return "All lines checked. Ready to sign.";
  return `${String(left)} ${left === 1 ? "line needs" : "lines need"} you before you sign.`;
}

/** Why the line has the status it has, in plain words. */
export function reasonFor(line: DraftLine): string {
  switch (line.review) {
    case "confirmed":
      return "You confirmed this wording.";
    case "edited":
      return "You edited this line. Code checked it again when you saved.";
    case "removed":
      return "You removed this line. It won't be in the signed note.";
    case "pending":
      break;
  }
  switch (line.status) {
    case "source_found":
      return "The words this line came from are in your note, and its numbers match.";
    case "summary":
      return "The AI wrote this in its own words, from the words below. Code found those words in your note, but it can't check the meaning. Read it before you sign.";
    case "number_mismatch": {
      if (line.number_mismatches.length === 0)
        return "A number in this line differs from your note.";
      return line.number_mismatches
        .map((m) =>
          m.note_text === null
            ? `The draft says ${m.draft_text}. Your note has no number to match it.`
            : `The draft says ${m.draft_text}. Your note says ${m.note_text}.`,
        )
        .join(" ");
    }
    case "no_source":
      return "Nothing in your note says this. The AI added it. Remove it, or add it to your note first if you did it.";
  }
}

// ---------------------------------------------------------------------------------------------
// What the nurse can do to a line, and the signed view.

export type LineAction =
  | { kind: "confirm" }
  | { kind: "remove" }
  | { kind: "edit" }
  | { kind: "undo" }
  | { kind: "putBack" }
  /** `replacement` is the note's number; `text` is the line with it in place of the draft's. */
  | { kind: "use"; replacement: string; text: string }
  /** Two or more differing numbers: every replacement in one edit, `replacements` left to right. */
  | { kind: "useAll"; replacements: string[]; text: string };

/** The buttons the trace card shows for a line, the one that settles it first. */
export function actionsFor(line: DraftLine): LineAction[] {
  switch (line.review) {
    case "removed":
      return [{ kind: "putBack" }];
    case "confirmed":
    case "edited":
      return [{ kind: "undo" }, { kind: "edit" }];
    case "pending":
      break;
  }
  switch (line.status) {
    case "summary":
      return [{ kind: "confirm" }, { kind: "edit" }];
    case "number_mismatch": {
      const fixable = line.number_mismatches.flatMap((m) =>
        m.note_text === null ? [] : [{ span: m.draft_span, replacement: m.note_text }],
      );
      const [only, second] = fixable;
      if (only && !second) {
        const text = replaceAtSpan(line.text, only.span, only.replacement);
        return [{ kind: "use", replacement: only.replacement, text }, { kind: "edit" }];
      }
      if (only && second) {
        // Right to left, so a replacement of another length can't move the spans still to come.
        const text = [...fixable]
          .sort((a, b) => b.span.start - a.span.start)
          .reduce((soFar, f) => replaceAtSpan(soFar, f.span, f.replacement), line.text);
        const replacements = [...fixable]
          .sort((a, b) => a.span.start - b.span.start)
          .map((f) => f.replacement);
        return [{ kind: "useAll", replacements, text }, { kind: "edit" }];
      }
      return [{ kind: "edit" }];
    }
    case "no_source":
      // A Focus line is the heading of its entry: it can be reworded, not removed.
      return line.section === "focus" ? [{ kind: "edit" }] : [{ kind: "remove" }];
    case "source_found":
      return [{ kind: "edit" }];
  }
}

/** The draft as the record has it once signed: the lines the nurse removed are not in it. */
export function withoutRemoved(draft: Draft): Draft {
  const kept = (lines: DraftLine[]) => lines.filter((l) => l.review !== "removed");
  return {
    ...draft,
    entries: draft.entries.map((entry) => ({
      ...entry,
      data: kept(entry.data),
      action: kept(entry.action),
      response: kept(entry.response),
    })),
  };
}
