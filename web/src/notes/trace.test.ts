import { describe, expect, it } from "vitest";
import type { components } from "../api/schema";
import { demoApi } from "../mocks/demo-api";
import {
  answerText,
  lineSegments,
  linesInOrder,
  needsReview,
  nextLineNeedingReview,
  noteMarks,
  quoteSegments,
  reasonFor,
  shownStatus,
  spansFor,
  wordsAt,
} from "./trace";

type Line = components["schemas"]["DraftLine"];
type Draft = components["schemas"]["FdarDraft"];

function demoNote(id: string) {
  const found = demoApi.notes[id];
  if (!found) throw new Error(`no demo note ${id}`);
  return found;
}
const DEMO_1 = demoNote("00000000-0000-4000-8000-000000000015");
const DEMO_2 = demoNote("00000000-0000-4000-8000-000000000025");

/** A line of demo-1's draft by its id. */
function demoLine(id: string): Line {
  const found = linesInOrder(DEMO_1.draft).find((l) => l.id === id);
  if (!found) throw new Error(`no demo line ${id}`);
  return found;
}

function line(over: Partial<Line> = {}): Line {
  return {
    id: "x",
    section: "data",
    text: "Some line.",
    ai_text: "Some line.",
    status: "source_found",
    review: "pending",
    source_quotes: [],
    number_mismatches: [],
    ...over,
  };
}

function draftOf(...lines: Line[]): Draft {
  const [focus, ...rest] = lines;
  return {
    entries: [{ focus: focus ?? line(), data: rest, action: [], response: [] }],
  };
}

describe("spansFor", () => {
  it("returns one plain segment when there are no marks", () => {
    expect(spansFor("pt c/o hilo", [])).toEqual([
      { highlight: null, parts: [{ text: "pt c/o hilo", bad: false }] },
    ]);
  });

  it("slices by code point after an emoji", () => {
    // The emoji is one code point but two UTF-16 units: text.slice would be off by one.
    const text = "😀 BP 90/60 HR 112";
    const segments = spansFor(text, [{ kind: "highlight", start: 2, end: 11, index: 0 }]);
    expect(segments).toEqual([
      { highlight: null, parts: [{ text: "😀 ", bad: false }] },
      { highlight: 0, parts: [{ text: "BP 90/60 ", bad: false }] },
      { highlight: null, parts: [{ text: "HR 112", bad: false }] },
    ]);
  });

  it("overlapping quotes merge into one mark", () => {
    const segments = spansFor("abcdefghij", [
      { kind: "highlight", start: 1, end: 5, index: 0 },
      { kind: "highlight", start: 3, end: 8, index: 1 },
    ]);
    expect(segments).toEqual([
      { highlight: null, parts: [{ text: "a", bad: false }] },
      { highlight: 0, parts: [{ text: "bcdefgh", bad: false }] },
      { highlight: null, parts: [{ text: "ij", bad: false }] },
    ]);
  });

  it("merges highlights that only touch, and keeps the lowest quote index", () => {
    const segments = spansFor("abcdef", [
      { kind: "highlight", start: 3, end: 6, index: 2 },
      { kind: "highlight", start: 0, end: 3, index: 1 },
    ]);
    expect(segments).toEqual([{ highlight: 1, parts: [{ text: "abcdef", bad: false }] }]);
  });

  it("keeps highlights with a gap between them as two marks", () => {
    const segments = spansFor("abcdef", [
      { kind: "highlight", start: 0, end: 2, index: 0 },
      { kind: "highlight", start: 3, end: 5, index: 1 },
    ]);
    expect(segments.map((s) => s.highlight)).toEqual([0, null, 1, null]);
  });

  it("marks the differing number inside its quote", () => {
    const text = "pt BP 90/60 HR 112.";
    const segments = spansFor(text, [
      { kind: "highlight", start: 3, end: 18, index: 0 },
      { kind: "bad", start: 15, end: 18 },
    ]);
    expect(segments).toEqual([
      { highlight: null, parts: [{ text: "pt ", bad: false }] },
      {
        highlight: 0,
        parts: [
          { text: "BP 90/60 HR ", bad: false },
          { text: "112", bad: true },
        ],
      },
      { highlight: null, parts: [{ text: ".", bad: false }] },
    ]);
  });

  it("marks a differing number that sits outside any highlight", () => {
    const segments = spansFor("abc 112", [{ kind: "bad", start: 4, end: 7 }]);
    expect(segments).toEqual([
      {
        highlight: null,
        parts: [
          { text: "abc ", bad: false },
          { text: "112", bad: true },
        ],
      },
    ]);
  });

  it("ignores empty, backwards and out-of-range spans, and clamps the rest", () => {
    const segments = spansFor("abcd", [
      { kind: "highlight", start: 2, end: 2, index: 0 },
      { kind: "highlight", start: 3, end: 1, index: 1 },
      { kind: "highlight", start: -5, end: 2, index: 2 },
      { kind: "highlight", start: 3, end: 99, index: 3 },
    ]);
    expect(segments.map((s) => [s.highlight, s.parts.map((p) => p.text).join("")])).toEqual([
      [2, "ab"],
      [null, "c"],
      [3, "d"],
    ]);
  });

  it("returns no segments for no text", () => {
    expect(spansFor("", [{ kind: "highlight", start: 0, end: 3, index: 0 }])).toEqual([]);
  });
});

describe("shownStatus", () => {
  const pending: [Line["status"], string, string, string][] = [
    ["source_found", "Source found", "ok", "check"],
    ["summary", "AI wording — check", "review", "pen"],
    ["number_mismatch", "Number differs", "stop", "neq"],
    ["no_source", "Not in your note", "stop", "flag"],
  ];
  it.each(pending)("a pending %s line reads %s", (status, label, tone, icon) => {
    expect(shownStatus(line({ status, review: "pending" }))).toEqual({
      key: status,
      label,
      tone,
      icon,
    });
  });

  const statuses: Line["status"][] = ["source_found", "summary", "number_mismatch", "no_source"];
  it.each(statuses)("a confirmed %s line is Checked by you", (status) => {
    expect(shownStatus(line({ status, review: "confirmed" }))).toMatchObject({
      key: "confirmed",
      label: "Checked by you",
      tone: "you",
      icon: "you",
    });
  });
  it.each(statuses)(
    "an edited %s line is Edited by you, whatever it was re-checked as",
    (status) => {
      expect(shownStatus(line({ status, review: "edited" }))).toMatchObject({
        key: "edited",
        label: "Edited by you",
        tone: "you",
        icon: "pen",
      });
    },
  );
  it.each(statuses)("a removed %s line is Removed by you", (status) => {
    expect(shownStatus(line({ status, review: "removed" }))).toMatchObject({
      key: "removed",
      label: "Removed by you",
      tone: "muted",
      icon: "removed",
    });
  });
});

describe("needsReview", () => {
  it("is false for a pending line whose source was found", () => {
    expect(needsReview(line({ status: "source_found" }))).toBe(false);
  });
  it.each(["summary", "number_mismatch", "no_source"] as const)(
    "is true for a pending %s line",
    (status) => {
      expect(needsReview(line({ status }))).toBe(true);
    },
  );
  it.each(["confirmed", "edited", "removed"] as const)("is false once %s", (review) => {
    expect(needsReview(line({ status: "no_source", review }))).toBe(false);
  });
});

describe("answerText", () => {
  it("counts the lines that need you, in the plural", () => {
    expect(answerText(DEMO_1.draft, "draft")).toBe("3 lines need you before you sign.");
  });
  it("says 1 line needs you", () => {
    const draft = draftOf(line({ id: "a", status: "summary" }), line({ id: "b" }));
    expect(answerText(draft, "draft")).toBe("1 line needs you before you sign.");
  });
  it("says it is ready when nothing needs you", () => {
    const draft = draftOf(line({ id: "a", status: "summary", review: "confirmed" }), line());
    expect(answerText(draft, "draft")).toBe("All lines checked. Ready to sign.");
  });
  it("says a signed note is locked, whatever its lines say", () => {
    expect(answerText(DEMO_1.draft, "signed")).toBe("Signed. This note is locked.");
  });
  it("says a discarded draft won't reach the record", () => {
    expect(answerText(DEMO_1.draft, "discarded")).toBe(
      "Discarded. This draft won't reach the record.",
    );
  });
});

describe("linesInOrder", () => {
  it("goes focus, data, action, response for each entry in turn", () => {
    expect(linesInOrder(DEMO_1.draft).map((l) => l.id)).toEqual([
      "e1-F",
      "e1-D1",
      "e1-D2",
      "e1-D3",
      "e1-D4",
      "e1-D5",
      "e1-A1",
      "e1-A2",
      "e1-R1",
    ]);
  });
  it("walks every entry of a note with two", () => {
    const ids = linesInOrder(DEMO_2.draft).map((l) => l.id);
    expect(ids.indexOf("e2-F")).toBeGreaterThan(ids.indexOf("e1-R1"));
    expect(ids.at(-1)).toBe("e2-A2");
  });
});

describe("nextLineNeedingReview", () => {
  it("finds the first line that needs you when nothing is selected", () => {
    expect(nextLineNeedingReview(DEMO_1.draft)?.id).toBe("e1-F");
  });
  it("finds the next one after the given line", () => {
    expect(nextLineNeedingReview(DEMO_1.draft, "e1-F")?.id).toBe("e1-D2");
    expect(nextLineNeedingReview(DEMO_1.draft, "e1-D2")?.id).toBe("e1-A2");
  });
  it("wraps around to the start", () => {
    expect(nextLineNeedingReview(DEMO_1.draft, "e1-A2")?.id).toBe("e1-F");
  });
  it("starts from the top when the id is unknown", () => {
    expect(nextLineNeedingReview(DEMO_1.draft, "nope")?.id).toBe("e1-F");
  });
  it("comes back to the same line when it is the only one", () => {
    const draft = draftOf(line({ id: "a" }), line({ id: "b", status: "no_source" }));
    expect(nextLineNeedingReview(draft, "b")?.id).toBe("b");
  });
  it("is undefined when no line needs you", () => {
    const draft = draftOf(line({ id: "a" }), line({ id: "b", review: "confirmed" }));
    expect(nextLineNeedingReview(draft, "a")).toBeUndefined();
  });
});

describe("reasonFor", () => {
  const byId = demoLine;

  it("says a found source matches", () => {
    expect(reasonFor(byId("e1-D1"))).toBe(
      "The words this line came from are in your note, and its numbers match.",
    );
  });
  it("says what the AI did for a summary line", () => {
    expect(reasonFor(byId("e1-F"))).toMatch(/^The AI wrote this in its own words/);
  });
  it("gives both numbers for a mismatch", () => {
    expect(reasonFor(byId("e1-D2"))).toBe("The draft says 121. Your note says 112.");
  });
  it("says so when the note has no number to match", () => {
    const l = line({
      status: "number_mismatch",
      number_mismatches: [
        {
          kind: "value",
          draft_text: "121",
          draft_span: { start: 0, end: 3 },
          note_text: null,
          note_span: null,
        },
      ],
    });
    expect(reasonFor(l)).toBe("The draft says 121. Your note has no number to match it.");
  });
  it("gives every mismatch of a line", () => {
    const l = line({
      status: "number_mismatch",
      number_mismatches: [
        {
          kind: "value",
          draft_text: "121",
          draft_span: { start: 0, end: 3 },
          note_text: "112",
          note_span: { start: 0, end: 3 },
        },
        {
          kind: "unit",
          draft_text: "37.8 °F",
          draft_span: { start: 5, end: 12 },
          note_text: "37.8",
          note_span: { start: 5, end: 9 },
        },
      ],
    });
    expect(reasonFor(l)).toBe(
      "The draft says 121. Your note says 112. The draft says 37.8 °F. Your note says 37.8.",
    );
  });
  it("still says something when a mismatch line lists no numbers", () => {
    expect(reasonFor(line({ status: "number_mismatch" }))).toBe(
      "A number in this line differs from your note.",
    );
  });
  it("says nothing in the note supports an unsourced line", () => {
    expect(reasonFor(byId("e1-A2"))).toMatch(/^Nothing in your note says this/);
  });
  it("explains a confirmed, edited and removed line", () => {
    expect(reasonFor(line({ review: "confirmed" }))).toBe("You confirmed this wording.");
    expect(reasonFor(line({ review: "edited", status: "no_source" }))).toBe(
      "You edited this line. Code checked it again when you saved.",
    );
    expect(reasonFor(line({ review: "removed" }))).toBe(
      "You removed this line. It won't be in the signed note.",
    );
  });
});

describe("what a selected line lights up", () => {
  const d1 = demoLine;

  it("highlights each found quote, numbered in order, and marks the note's differing number", () => {
    expect(noteMarks(d1("e1-D2"))).toEqual([
      { kind: "highlight", start: 23, end: 38, index: 0 },
      { kind: "bad", start: 35, end: 38 },
    ]);
    expect(noteMarks(d1("e1-F"))).toEqual([
      { kind: "highlight", start: 3, end: 21, index: 0 },
      { kind: "highlight", start: 23, end: 31, index: 1 },
    ]);
  });

  it("lights up nothing for a line with no source, or a removed one", () => {
    expect(noteMarks(d1("e1-A2"))).toEqual([]);
    const removed = line({
      review: "removed",
      source_quotes: [{ text: "a", span: { start: 0, end: 1 } }],
    });
    expect(noteMarks(removed)).toEqual([]);
  });

  it("skips a quote the server gave no span for", () => {
    expect(noteMarks(line({ source_quotes: [{ text: "pt c/o", span: null }] }))).toEqual([]);
  });

  it("marks the draft's own differing number inside the line's text", () => {
    const parts = lineSegments(d1("e1-D2")).flatMap((s) => s.parts);
    expect(parts.filter((p) => p.bad).map((p) => p.text)).toEqual(["121"]);
    expect(parts.map((p) => p.text).join("")).toBe(d1("e1-D2").text);
  });

  it("leaves a line with no mismatch unmarked", () => {
    expect(
      lineSegments(d1("e1-D1"))
        .flatMap((s) => s.parts)
        .some((p) => p.bad),
    ).toBe(false);
  });

  it("marks the note's number inside the quote it belongs to", () => {
    const segments = quoteSegments(d1("e1-D2"), 0);
    expect(segments[0]?.highlight).toBe(0);
    const bad = segments.flatMap((s) => s.parts).filter((p) => p.bad);
    expect(bad.map((p) => p.text)).toEqual(["112"]);
  });

  it("cuts the words at a span by code point", () => {
    expect(wordsAt("😀 BP 90/60", { start: 2, end: 7 })).toBe("BP 90");
    expect(wordsAt("abc", { start: 2, end: 99 })).toBe("c");
  });
});
