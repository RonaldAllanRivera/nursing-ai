"""Deciding each draft line's status from its quotes, numbers and units.

Numbers are read from the note as typed, never from the normalised matching text, so a character
the matcher folds (a typed "½", say) can't make a number appear that the nurse didn't write. A
number counts for a quote when it overlaps the quote and is compared whole; labels are read only
inside the quote, and a unit is read right after the number even past the quote's end. A line
number written with no unit is never checked for one: "PO intake 8." passes for the note's
"8 oz", while "PO intake 8 mL." is flagged for its unit. A word whose number can't be compared by
value ("q4h", "D5W", "two") must appear whole in a found quote.
A frequency ("daily", "every day", "twice a day", "BID") is read by meaning and needs a frequency
of the same meaning in a found quote. One that no quote gives is flagged whole, as typed ("3 times
a day"), in place of any number or number-word mismatch it overlaps, so a one-click fix of a
number can't keep a wrong period; one the quotes give leaves those mismatches as they are. A time
word right after a line's number ("every 2 hours") needs the same time, by meaning, right after a
note number of that value ("q 2 hrs").

A number's label is the word right before it, or a two-word label from the table of measures
("heart rate", "pulse rate") as a whole, read past one ":" or "=", one "~" or "(" and a comparator
("HR: ~88", "HR (>100)"), and past a joining word ("is", "was", "at", "of": "HR is 88"). "At" is
read past only when the number after it is a value: for a clock time ("0600", "2400", "10:30",
"2pm") or a number with a dose, volume, drop or oxygen-flow unit ("2L"), and for a joining word
with no label before it ("at 0800"), the word is itself the label. Labels are read only in the
quotes, from the last few characters before the number.

A number with no label of its own, written right after an arrow ("HR 88->110", with only spaces,
the arrow and its own comparator after the previous number and its unit), takes that number's label
when both are written alike: both "/" groups or neither, and the same written right after each,
compared in any case and without spaces, and read even past the quote's end. What is written right
after a number is the unit (one the code reads or only knows) or the rate read there, as typed
("°C", "bpm", "/hr"). With neither, a run of punctuation only right after the number is skipped
and what follows it is read in its place: dashes (a hyphen, an en or an em dash), ":", "(", "!",
"?" and ellipses ("..." or the one character for it), glued to the number or after spaces and
ending where a run ends (below), as in "HR 88->110 - MD notified" and "HR 88->110: improving".
Then a label of the table of measures (one word or two, read as any label is) that the joiners
above and a number follow starts the next reading and is nothing ("HR 88->110 RR 20", "HR 88->110
resp rate 20", "HR 88->110 - RR 20"), unless it is glued to that number (a letter right before
it: "O2", "RR20") or that number is a setting, written with a dose, volume, drop or oxygen-flow
unit ("sat 2L"). Anything else is the run of characters glued there or after spaces (of any kind
but a line break), up to a space, a line break, ",", ";", ")", an arrow or a "." that ends a
sentence (one followed by a space, a line break or the end): "°" for "38.5°", "*C" for "38.5*C",
"i.u" for "4 i.u.", "o2" for "94 O2", "MD" for "110 - MD notified". An arrow, the end of the text
or that punctuation there is nothing ("HR 88->110!", "HR 88->110 -"). A run longer than 64
characters is alike to none. So "HR 88 bpm -> 110 bpm", "SpO2 88%->95%", "HR 88->110, RR 20" and
"HR 88->110 - RR 20" take the label; "Pain 8/10 -> 2 mg", "HR 88 -> 20 cpm", "HR 88 -> 38.5°",
"HR 120 -> 94 sats", "HR 88->110 - MD notified" and "Pain 8 -> 2 - tabs" do not.

A label the quotes use says which of their numbers the line's number must be: under that label
the line's value must be one of theirs. A measure spelled another way is the same measure ("Temp"
for "T", "heart rate" for "HR"), so when the quotes give that measure numbers, a value that is not
one of them is a swap. When they give a measure of the table no number at all, a value they give
only under other measures of the table is a swap too ("Temp 88." for "HR 88 RR 20"). A wrong
value offers the note number of its label, else of its measure, when there is one, but none when
a quoted number of the line's value has no label of the table ("HR 110." for "HR was 88, now
110"): the line may mean that reading, and a one-click fix would write an older one over it. A
comparator (">", "<", ">=", "<=", "≥", "≤") right before a number belongs to it, even when it
stands before the quote starts, and is compared by meaning (">=" is "≥"); an arrow ("->", "-->",
"=>") and "~" are not comparators. A line number whose value matches must carry the comparator,
or none, of a note number of that value: "HR 100" for "HR >100" is flagged, naming ">100".
Comparator words ("above", "over", "below") are not read, as "over" is also "120 over 80".
"""

import re
from bisect import bisect_left, bisect_right
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from nursing_core.domain.model_output import ModelLine
from nursing_core.domain.notes import (
    DraftLine,
    FdarSection,
    LineReview,
    LineStatus,
    MismatchKind,
    NumberMismatch,
    SourceQuote,
    Span,
)
from nursing_core.domain.units import (
    TEMPERATURE_UNITS,
    VOLUME_UNITS,
    WEIGHT_UNITS,
    Ucum,
    UnitDefaults,
)
from nursing_core.pipeline.text import MatchText, find_span
from nursing_core.pipeline.unit_check import (
    NumberValue,
    WrittenUnit,
    bare_rate_end_after,
    frequencies_in,
    number_value,
    numbers_in,
    time_after,
    words_with_numbers,
    written_unit,
)

# A comparator written right before a number; the "-" and "=" keep "->", "-->" and "=>" arrows out.
_COMPARATOR = r"(?<![-=])(?:>=|<=|≥|≤|>|<)"
# The joining words that may stand between a label and its number ("HR is 88"), with and without
# "at", which is read past only when its number is a value and not a time or a setting.
_JOINING_WORD = (
    r"(?:[ \t]+(?:is|was|of)(?![^\W_]))?",
    r"(?:[ \t]+(?:is|was|at|of)(?![^\W_]))?",
)
# What else may stand there, each part optional and in this order: one ":" or "=", one "~" or "(",
# a comparator, with spaces or tabs between any of them. No part starts with what another part or
# a space starts with, so the parts are read once, whole ("(?>"), and a long run of spaces that
# is not followed by the number fails at once.
_JOINERS = (
    r"(?>"
    r"[ \t]*[:=]?"  # "HR: 88"
    r"[ \t]*[~(]?"  # "HR ~88", "HR (88)"
    rf"[ \t]*(?:{_COMPARATOR})?"  # "HR >100"
    r"[ \t]*)$"
)
# The word right before a number, and the two words right before it ("heart rate").
_ONE_WORD = r"(?<!\w)([^\W\d_][^\W_]*)"
_TWO_WORDS = r"(?<!\w)([^\W\d_][^\W_]*[ \t]+[^\W\d_][^\W_]*)"
# The label patterns, indexed by whether "at" is read past.
_LABEL = tuple(re.compile(_ONE_WORD + word + _JOINERS, re.IGNORECASE) for word in _JOINING_WORD)
_TWO_WORD_LABEL = tuple(
    re.compile(_TWO_WORDS + word + _JOINERS, re.IGNORECASE) for word in _JOINING_WORD
)
# A clock time written after a number: "10:30", "2pm", "10 am".
_CLOCK_AFTER = re.compile(r"(?::\d\d|[ \t]*[ap]\.?m(?![^\W_]))", re.IGNORECASE)
# A clock time written as four digits: "0600", "2400".
_CLOCK_DIGITS = re.compile(r"(?:[01]\d|2[0-3])[0-5]\d|2400")
# Only an arrow between two numbers, and the second one's own comparator: "HR 88 -> >110".
_ARROW = re.compile(rf"[ \t]*(?:-{{1,2}}>|=>)[ \t]*(?:{_COMPARATOR}[ \t]*)?")
# A space: any whitespace but a line break (the ones `str.splitlines` breaks at).
_SPACE = r"[^\S\n\r\v\f\x1c-\x1e\x85\u2028\u2029]"
# One character of what is written right after a number: not a space, a line break, ",", ";" or
# ")"; a "." only when more follows it ("i.u."), and a "-" or "=" only when no arrow starts there.
_RUN_CHARACTER = r"(?:[^\s,;).=-]|\.(?=\S)|-(?!-?>)|=(?!>))"
# How many characters of what is written right after a number are read.
_READ_AFTER = 64
# What is written right after a number, glued to it or after spaces: up to `_READ_AFTER`
# characters of it, then one more when it goes on past them.
_RUN_AFTER = re.compile(rf"{_SPACE}*({_RUN_CHARACTER}{{1,{_READ_AFTER}}})({_RUN_CHARACTER})?")
# A mark of punctuation only: a dash (a hyphen where no arrow starts, an en or an em dash), ":",
# "(", "!", "?" or an ellipsis ("..." or the one character for it).
_MARK = r"(?:-(?!-?>)|[\u2013\u2014:(!?\u2026]|\.\.\.)"
# A run of marks only right after a number, glued to it or after spaces, to where the run ends:
# the " -" of "110 - MD notified", the ":" of "110: improving", the "!" of "110!". It is skipped.
_MARKS_AFTER = re.compile(rf"{_SPACE}*{_MARK}+(?!{_RUN_CHARACTER})")
# Spaces after a number, a label of one word or two, then the joiners before the next number
# ("110 RR 20"), indexed by whether "at" is read past.
_LABEL_AFTER = tuple(
    re.compile(f"{_SPACE}*{_ONE_WORD}{word}{_JOINERS}", re.IGNORECASE) for word in _JOINING_WORD
)
_TWO_WORD_LABEL_AFTER = tuple(
    re.compile(f"{_SPACE}*{_TWO_WORDS}{word}{_JOINERS}", re.IGNORECASE) for word in _JOINING_WORD
)
# How far back from a number its label, joiners and comparator are looked for.
_LOOK_BACK = 64
# A comparator right before a number, and the spaces between them.
_COMPARATOR_BEFORE = re.compile(rf"({_COMPARATOR})[ \t]*$")
# What a label measures, in the spellings a ward or the model uses, so "Temp 88, heart rate 37.8"
# can't take its values from "T 37.8 HR 88".
_MEASURES = {
    **dict.fromkeys(("t", "temp", "temperature", "bt"), "temp"),
    **dict.fromkeys(("hr", "pr", "pulse", "pulse rate", "heart rate"), "pulse"),
    **dict.fromkeys(
        (
            "rr",
            "resp",
            "resps",
            "resp rate",
            "respiratory rate",
            "respiration rate",
            "respirations",
            "respiration",
        ),
        "resp",
    ),
    **dict.fromkeys(("bp", "blood pressure"), "bp"),
    **dict.fromkeys(("spo2", "sat", "sats", "o2 sat", "oxygen saturation"), "spo2"),
    **dict.fromkeys(("i", "in", "intake"), "intake"),
    **dict.fromkeys(("o", "out", "output", "uo", "urine output"), "output"),
    **dict.fromkeys(("wt", "weight"), "weight"),
    **dict.fromkeys(("cbg", "rbs", "fbs", "glucose", "blood sugar"), "glucose"),
}

_PRECEDENCE = (
    LineStatus.NO_SOURCE,
    LineStatus.NUMBER_MISMATCH,
    LineStatus.SUMMARY,
    LineStatus.SOURCE_FOUND,
)


@dataclass(frozen=True, slots=True)
class _NoteNumber:
    value: NumberValue
    text: str
    span: Span  # in the note as typed
    label: str | None  # the label right before it, folded ("hr", "heart rate")
    measure: str | None  # what its label measures ("temp" for "T" and "Temperature")
    unit: WrittenUnit | None  # the unit written after it, if any
    bare_rate: tuple[str, ...]  # a rate written right after it with no unit ("100/hr")
    with_unit: Span  # the number and the unit written after it, in the note as typed
    typed_with_unit: str
    time: str | None  # the time word written right after it, by meaning ("hour" for "hrs")
    typed_with_time: str  # the number and that time word, as typed ("8 hrs")
    with_time: Span
    comparator: str | None  # the comparator written right before it, by meaning ("≥" for ">=")
    typed_with_comparator: str  # that comparator and the number, as typed (">= 100")
    with_comparator: Span


def check_line(
    line_id: str, section: FdarSection, model_line: ModelLine, note: MatchText, units: UnitDefaults
) -> DraftLine:
    quotes = [SourceQuote(text=q, span=find_span(note, q)) for q in model_line.source_quotes]
    status, mismatches = _assess(model_line.text, quotes, model_line.own_wording, note, units)
    return DraftLine(
        id=line_id,
        section=section,
        text=model_line.text,
        ai_text=model_line.text,
        status=status,
        review=LineReview.PENDING,
        source_quotes=quotes,
        number_mismatches=mismatches,
    )


def recheck_line(line: DraftLine, new_text: str, note: MatchText, units: UnitDefaults) -> DraftLine:
    """The nurse's edit is her own words, so it is never "AI wording"."""
    status, mismatches = _assess(new_text, line.source_quotes, False, note, units)
    return line.model_copy(
        update={
            "text": new_text,
            "status": status,
            "number_mismatches": mismatches,
            "review": LineReview.EDITED,
        }
    )


def restore_line(line: DraftLine, note: MatchText, units: UnitDefaults) -> DraftLine:
    """Put the AI text back. Whether the model called it its own wording isn't kept, so take the
    more cautious of the two readings."""
    readings = [
        _assess(line.ai_text, line.source_quotes, own_wording, note, units)
        for own_wording in (True, False)
    ]
    status, mismatches = min(readings, key=lambda reading: _PRECEDENCE.index(reading[0]))
    return line.model_copy(
        update={
            "text": line.ai_text,
            "status": status,
            "number_mismatches": mismatches,
            "review": LineReview.PENDING,
        }
    )


def _assess(
    text: str,
    quotes: list[SourceQuote],
    own_wording: bool,
    note: MatchText,
    units: UnitDefaults,
) -> tuple[LineStatus, list[NumberMismatch]]:
    spans = [quote.span for quote in quotes]
    found = [span for span in spans if span is not None]
    if len(found) < len(spans) or (not own_wording and not quotes):
        return LineStatus.NO_SOURCE, []
    note_numbers = _note_numbers(note.raw, found)
    quote_texts = [note.raw[span.start : span.end] for span in found]
    mismatches = _mismatches(text, note_numbers, quote_texts, units)
    if mismatches:
        return LineStatus.NUMBER_MISMATCH, mismatches
    return (LineStatus.SUMMARY if own_wording else LineStatus.SOURCE_FOUND), []


def _look_back(text: str, start: int, end: int) -> str:
    """The last few characters of text[start:end], cut at a word boundary."""
    low = max(start, end - _LOOK_BACK)
    piece = text[low:end]
    if low > start and text[low - 1].isalnum():
        piece = re.sub(r"^\w+", "", piece)
    return piece


@dataclass(frozen=True, slots=True)
class _Read:
    """What is written around one number of a text, read once."""

    written: str
    span: Span
    unit: WrittenUnit | None
    bare_rate: tuple[str, ...]  # a rate written right after it with no unit ("100/hr")
    bare_end: int  # where that rate ends (the number's end when there is none)
    end: int  # where the number ends, with its unit or rate and a "%" right after it
    # Whether it is a "/" group, and what is written after it, folded; None when that is too
    # long to read, so the number is written alike to no other.
    alike: tuple[bool, str] | None
    at_is_value: bool  # whether an "at" before it is read past ("HR at 88" but not "at 0600")


def _at_is_value(text: str, written: str, span: Span, unit: WrittenUnit | None) -> bool:
    """Whether an "at" before a number is read past: not before a clock time ("0600", "10:30",
    "2pm") or a setting, a number with a dose, volume, drop or oxygen-flow unit ("2L")."""
    return not (
        (unit is not None and unit.compared is not None)
        or _CLOCK_DIGITS.fullmatch(written)
        or _CLOCK_AFTER.match(text, span.end)
    )


def _label_after(text: str, start: int, end: int, past_at: bool) -> bool:
    """Whether text[start:end] is spaces, a label of the measures table and the joiners, read as
    a label before a number is: two words from the table as a whole, else one word."""
    two = _TWO_WORD_LABEL_AFTER[past_at].fullmatch(text, start, end)
    if two is not None and " ".join(two.group(1).casefold().split()) in _MEASURES:
        return True
    one = _LABEL_AFTER[past_at].fullmatch(text, start, end)
    return one is not None and one.group(1).casefold() in _MEASURES


def _starts_the_next_reading(
    text: str, start: int, number: tuple[str, Span], unit: Callable[[], WrittenUnit | None]
) -> bool:
    """Whether all that is written from `start` to the next number is a label of the measures
    table and the joiners before that number ("HR 88->110 RR 20", "110 resp rate is 20").

    The label is looked for as far back as any label is, and is not glued to the number ("O2",
    "RR20"). The number is no setting, written with a dose, volume, drop or oxygen-flow unit
    ("sat 2L"), and an "at" there is read past only when the number is a value. `unit` reads the
    number's unit, only once the label is found.
    """
    written, span = number
    if span.start - start > _LOOK_BACK or text[span.start - 1].isalpha():
        return False
    without_at = _label_after(text, start, span.start, past_at=False)
    if not without_at and not _label_after(text, start, span.start, past_at=True):
        return False
    read = unit()
    if read is not None and read.compared is not None:
        return False
    return without_at or _at_is_value(text, written, span, read)


def _written_after(text: str, span: Span, end: int, after: int, next_reading: bool) -> str | None:
    """What is written right after a number, folded, for telling whether two are written alike.

    A unit or a rate read after the number (up to `end`) is its typed spelling in any case and
    without spaces ("°C" is "°c", "/ hr" is "/hr"). Otherwise what is read starts at `after`, past
    a run of punctuation only right after the number ("-", ":", "!", "..."): a label of the
    measures table that the next number follows starts the next reading and is nothing
    (`next_reading`); and anything else is the run of characters glued to that place or after
    spaces, up to a space, a line break, ",", ";", ")", an arrow or a "." that ends a sentence
    ("°", "*c", "tabs", "i.u", "o2", the "md" of "110 - MD notified"). It is nothing when an
    arrow, the end of the text or that punctuation comes first, and None when it is longer than
    can be read.
    """
    if end > span.end:
        return "".join(text[span.end : end].split()).casefold()
    if next_reading:
        return ""
    run = _RUN_AFTER.match(text, after)
    if run is None:
        return ""
    return None if run.group(2) is not None else run.group(1).casefold()


def _reads(
    text: str, tokens: list[tuple[str, Span]], first: int = 0, stop: int | None = None
) -> list[_Read]:
    """The numbers tokens[first:stop] of the text with what is written around each, each read once.

    `tokens` are all the numbers of the text, so what follows the last one read is seen too, up
    to the next number. A label there is looked for only when the last one comes right after an
    arrow, the only case where what follows it is compared (`_labels`), and only then is the
    next number's unit read.
    """
    stop = len(tokens) if stop is None else stop
    units = [written_unit(text, span) for _, span in tokens[first:stop]]

    def unit_at(index: int) -> WrittenUnit | None:
        """The unit after tokens[index]: read above in the range, read here past it."""
        return units[index - first] if index < stop else written_unit(text, tokens[index][1])

    out: list[_Read] = []
    for index in range(first, stop):
        written, span = tokens[index]
        unit = units[index - first]
        bare_rate, bare_end = bare_rate_end_after(text, span)
        end = bare_end if unit is None else unit.end
        # With no unit or rate after it, a run of punctuation only right after the number is
        # skipped: what follows it is read in its place ("110 - RR 20", "110 - MD notified").
        marks = _MARKS_AFTER.match(text, span.end) if end == span.end else None
        after = span.end if marks is None else marks.end()
        after_arrow = bool(out) and _ARROW.fullmatch(text, out[-1].end, span.start) is not None
        next_reading = (
            end == span.end
            and index + 1 < len(tokens)
            and (index + 1 < stop or after_arrow)
            and _starts_the_next_reading(
                text, after, tokens[index + 1], partial(unit_at, index + 1)
            )
        )
        key = _written_after(text, span, end, after, next_reading)
        out.append(
            _Read(
                written=written,
                span=span,
                unit=unit,
                bare_rate=bare_rate,
                bare_end=bare_end,
                end=end + (unit is None and text.startswith("%", end)),
                alike=None if key is None else ("/" in written, key),
                at_is_value=_at_is_value(text, written, span, unit),
            )
        )
    return out


def _label_before(text: str, past_at: bool) -> str | None:
    """The label right before a number, given the text up to it, folded.

    A two-word label from the measures table ("heart rate") is the label as a whole; any other
    label is the one word right before the number. A joining word is read past, "at" only when
    `past_at`: a clock time or a setting after "at" is not the value of the label before it.
    """
    two = _TWO_WORD_LABEL[past_at].search(text)
    if two is not None:
        words = " ".join(two.group(1).casefold().split())
        if words in _MEASURES:
            return words
    match = _LABEL[past_at].search(text)
    return None if match is None else match.group(1).casefold()


def _labels(text: str, reads: list[_Read], start: int = 0) -> dict[int, str | None]:
    """The label of each number that starts at or after `start`, by where it starts, in one pass.

    Labels are read only after `start`. A number with no label of its own, written right after
    an arrow ("HR 88->110", with only spaces, the arrow and its own comparator after the previous
    number and its unit), takes the previous number's label when the two are written alike: both
    "/" groups or neither, and the same written right after each (see `_written_after`).
    """
    labels: dict[int, str | None] = {}
    previous: tuple[str | None, _Read] | None = None
    for read in reads:
        if read.span.start < start:
            continue
        label = _label_before(_look_back(text, start, read.span.start), read.at_is_value)
        if label is None and previous is not None and read.alike is not None:
            before, last = previous
            if last.alike == read.alike and _ARROW.fullmatch(text, last.end, read.span.start):
                label = before
        labels[read.span.start] = label
        previous = (label, read)
    return labels


def _comparator_before(text: str, end: int) -> tuple[str, int] | None:
    """The comparator right before a number that starts at `end`: its meaning and its start.

    ">=" and "<=" mean "≥" and "≤".
    """
    low = max(0, end - _LOOK_BACK)
    match = _COMPARATOR_BEFORE.search(text[low:end])
    if match is None:
        return None
    return {">=": "≥", "<=": "≤"}.get(match.group(1), match.group(1)), low + match.start(1)


def _note_numbers(raw: str, quote_spans: list[Span]) -> list[_NoteNumber]:
    """The numbers of the typed note that overlap a found quote, each compared whole.

    A quote that stops inside a number or its unit still brings in all of it; labels are read
    only inside the quote, and a comparator right before a number even past the quote's start.
    """
    out: list[_NoteNumber] = []
    tokens = numbers_in(raw)
    for quote in quote_spans:
        # The numbers that overlap the quote, which follow one another in `tokens`.
        first = bisect_right(tokens, quote.start, key=lambda token: token[1].end)
        stop = bisect_left(tokens, quote.end, key=lambda token: token[1].start)
        reads = _reads(raw, tokens, first, stop)
        labels = _labels(raw, reads, quote.start)
        for read in reads:
            written, span, unit = read.written, read.span, read.unit
            label = labels.get(span.start)
            with_unit = Span(start=span.start, end=read.bare_end if unit is None else unit.end)
            time = time_after(raw, span)
            with_time = Span(start=span.start, end=span.end if time is None else time[1])
            comparator = _comparator_before(raw, span.start)
            with_comparator = Span(
                start=span.start if comparator is None else comparator[1], end=span.end
            )
            out.append(
                _NoteNumber(
                    value=number_value(written),
                    text=written,
                    span=span,
                    label=label,
                    measure=None if label is None else _MEASURES.get(label, label),
                    unit=unit,
                    bare_rate=() if unit is not None else read.bare_rate,
                    with_unit=with_unit,
                    typed_with_unit=raw[with_unit.start : with_unit.end],
                    time=None if time is None else time[0],
                    typed_with_time=raw[with_time.start : with_time.end],
                    with_time=with_time,
                    comparator=None if comparator is None else comparator[0],
                    typed_with_comparator=raw[with_comparator.start : with_comparator.end],
                    with_comparator=with_comparator,
                )
            )
    return out


def default_unit(unit: Ucum, units: UnitDefaults) -> Ucum | None:
    if unit in TEMPERATURE_UNITS:
        return units.temperature
    if unit in WEIGHT_UNITS:
        return units.weight
    if unit in VOLUME_UNITS:
        return units.volume
    return None


def _same_unit(drafted: WrittenUnit, note: _NoteNumber, units: UnitDefaults) -> bool:
    """Whether the unit a note writes after a value agrees with the one the line writes after it.

    A unit the alias table reads must be the note's unit, or the facility's default when the note
    writes no unit at all. A dose or volume unit in the line must be the dose or volume unit the
    note writes after the value ("88 bpm" or "60 kg" can't source "88 units" or "60 mg"), and so
    must its rate: a bolus of 1000 units is not 1000 units per hour. A note number with no unit
    can only be the facility's default volume, mL ("IVF 100" is "100 mL", never "100 L", "100 mg"
    or "100 units"). A line's rate needs a rate in the note, whether after a unit or straight
    after the number ("100/hr"), and a rate the note writes straight after its number needs the
    same rate in a line that gives a dose or volume unit: "heparin 1000/hr" is not "1000 units".
    """
    written = note.unit
    if drafted.compared is not None:
        if written is None:
            if drafted.compared != "ml" or drafted.rate != note.bare_rate:
                return False
        elif written.compared != drafted.compared:
            return False
    if written is not None and written.rate != drafted.rate:
        return False
    if drafted.unit is not None:
        if written is None:
            if default_unit(drafted.unit, units) != drafted.unit:
                return False
        elif written.unit != drafted.unit:
            return False
    return True


def _note_rate(note: _NoteNumber) -> tuple[str, ...]:
    """The rate a note number is written with, after its unit or straight after the number."""
    return note.bare_rate if note.unit is None else note.unit.rate


def _in_a_quote(word: str, quote_texts: list[str]) -> bool:
    """Whether the word appears whole, in any case, in one of the quotes as typed."""
    pattern = re.compile(rf"(?<![^\W_]){re.escape(word.casefold())}(?![^\W_])")
    return any(pattern.search(quote.casefold()) for quote in quote_texts)


def _mismatches(
    text: str, note_numbers: list[_NoteNumber], quote_texts: list[str], units: UnitDefaults
) -> list[NumberMismatch]:
    out = [
        NumberMismatch(
            kind=MismatchKind.VALUE,
            draft_text=word,
            draft_span=span,
            note_text=None,
            note_span=None,
        )
        for word, span in words_with_numbers(text)
        if not _in_a_quote(word, quote_texts)
    ]
    reads = _reads(text, numbers_in(text))
    labels = _labels(text, reads)
    for read in reads:
        written, span, drafted = read.written, read.span, read.unit
        label = labels[span.start]
        value = number_value(written)
        # A label the quotes use for some number says which of their numbers this one must be,
        # whether the line spells it as they do or names the same measure another way ("Temp" for
        # "T", "heart rate" for "HR"): a value they give that measure under another label is a
        # swap. The units are compared with the numbers of the label as spelled, as before.
        measure = None if label is None else _MEASURES.get(label, label)
        labelled = [n for n in note_numbers if label is not None and n.label == label]
        measured = [n for n in note_numbers if measure is not None and n.measure == measure]
        same_value = [n for n in labelled or note_numbers if n.value == value]
        if measured:
            swapped = all(n.value != value for n in measured)
        else:
            # A measure of the table that the quotes give no number: a value they give only under
            # other measures of the table is a swap too ("Temp 88." for "HR 88 RR 20").
            swapped = (
                label in _MEASURES
                and bool(same_value)
                and all(n.label in _MEASURES for n in same_value)
            )
        if not same_value or swapped:
            paired = labelled[0] if labelled and not same_value else next(iter(measured), None)
            if any(n.value == value and n.label not in _MEASURES for n in note_numbers):
                # A quoted number of this value with no label of the table may be the reading
                # the line means ("HR 110." for "HR was 88, now 110"), so no note number is
                # offered: a one-click fix could write an older reading over it.
                paired = None
            out.append(
                NumberMismatch(
                    kind=MismatchKind.VALUE,
                    draft_text=written,
                    draft_span=span,
                    note_text=None if paired is None else paired.text,
                    note_span=None if paired is None else paired.span,
                )
            )
            continue
        comparator = _comparator_before(text, span.start)
        if all(n.comparator != (None if comparator is None else comparator[0]) for n in same_value):
            # ">100" needs a 100 the note writes with ">", and "100" a 100 it writes with none.
            named = same_value[0]
            start = span.start if comparator is None else comparator[1]
            out.append(
                NumberMismatch(
                    kind=MismatchKind.VALUE,
                    draft_text=text[start : span.end],
                    draft_span=Span(start=start, end=span.end),
                    note_text=named.typed_with_comparator,
                    note_span=named.with_comparator,
                )
            )
            continue
        time = time_after(text, span) if drafted is None else None
        if time is not None and all(n.time != time[0] for n in same_value):
            # "every 2 hours" needs a 2 the note writes with hours: the 2 of "2mg" isn't one.
            timed = [n for n in same_value if n.time is not None]
            named = timed[0] if timed else same_value[0]
            out.append(
                NumberMismatch(
                    kind=MismatchKind.UNIT,
                    draft_text=text[span.start : time[1]],
                    draft_span=Span(start=span.start, end=time[1]),
                    note_text=named.typed_with_time if timed else named.typed_with_unit,
                    note_span=named.with_time if timed else named.with_unit,
                )
            )
            continue
        # A note number that writes a unit settles it: a bare same-valued number can't excuse a
        # unit the nurse wrote differently elsewhere.
        candidates = [n for n in same_value if n.unit is not None] or same_value
        # A rate the note writes for this value must come back in the line, whatever rate-less
        # same-valued number the note also has, but only when the line writes a rate or a dose or
        # volume unit: a rate-less number can't excuse a rate the line drops or changes.
        rated = [n for n in same_value if _note_rate(n)]
        rates = {_note_rate(n) for n in rated}
        if drafted is None:
            rate, end = read.bare_rate, read.bare_end
            dropped = bool(rate) and bool(rates) and rate not in rates
        else:
            end = drafted.end
            dropped = bool(rated) and drafted.compared is not None and not drafted.rate
        if not dropped and (
            drafted is None or any(_same_unit(drafted, n, units) for n in candidates)
        ):
            continue
        line_rate = read.bare_rate if drafted is None else drafted.rate
        # The note number named is the one that carries a rate when the line writes one.
        first = rated[0] if dropped or (line_rate and rated) else candidates[0]
        out.append(
            NumberMismatch(
                kind=MismatchKind.UNIT,
                draft_text=text[span.start : end],
                draft_span=Span(start=span.start, end=end),
                note_text=first.typed_with_unit,
                note_span=first.with_unit,
            )
        )
    return sorted(_with_frequencies(text, quote_texts, out), key=lambda m: m.draft_span.start)


def _with_frequencies(
    text: str, quote_texts: list[str], found: list[NumberMismatch]
) -> list[NumberMismatch]:
    """The line's findings, where a frequency no found quote gives by meaning replaces them.

    That frequency becomes one finding over the whole frequency as typed, in place of every
    finding it overlaps ("twice" missing from the quotes, the "3" of "3 times a day" with the
    note's "2" beside it), so no one-click fix to a number can keep a wrong period. A frequency
    the quotes do give leaves the findings as they are.
    """
    in_the_quotes = {
        frequency.meaning for quote in quote_texts for frequency in frequencies_in(quote)
    }
    wrong = [f for f in frequencies_in(text) if f.meaning not in in_the_quotes]
    kept = [
        mismatch
        for mismatch in found
        if not any(
            f.span.start < mismatch.draft_span.end and mismatch.draft_span.start < f.span.end
            for f in wrong
        )
    ]
    return kept + [
        NumberMismatch(
            kind=MismatchKind.VALUE,
            draft_text=f.text,
            draft_span=f.span,
            note_text=None,
            note_span=None,
        )
        for f in wrong
    ]
