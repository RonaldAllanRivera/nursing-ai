"""Deciding each draft line's status from its quotes, numbers and units.

Numbers are read from the note as typed, never from the normalised matching text, so a character
the matcher folds (a typed "½", say) can't make a number appear that the nurse didn't write. A
number counts for a quote when it overlaps the quote and is compared whole; labels are read only
inside the quote, and a unit is read right after the number even past the quote's end. A word
whose number can't be compared by value ("q4h", "D5W", "two") must appear whole in a found quote.
A frequency ("daily", "every day", "twice a day", "BID") is read by meaning and needs a frequency
of the same meaning in a found quote; one that overlaps a mismatch the line already has is not
flagged again. A time word right after a line's number ("every 2 hours") needs the same time, by
meaning, right after a note number of that value ("q 2 hrs").
"""

import re
from dataclasses import dataclass

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

# The word right before a number; spaces and one ":" or "=" may sit between.
_LABEL = re.compile(r"(?<!\w)([^\W\d_][^\W_]*)[ \t]*[:=]?[ \t]*$")
# The two words right before a number, for a label such as "heart rate".
_TWO_WORD_LABEL = re.compile(r"(?<!\w)([^\W\d_][^\W_]*[ \t]+[^\W\d_][^\W_]*)[ \t]*[:=]?[ \t]*$")
# What a label measures, in the spellings a ward or the model uses, so "Temp 88, heart rate 37.8"
# can't take its values from "T 37.8 HR 88".
_MEASURES = {
    **dict.fromkeys(("t", "temp", "temperature", "bt"), "temp"),
    **dict.fromkeys(("hr", "pr", "pulse", "heart rate"), "pulse"),
    **dict.fromkeys(("rr", "resp", "resp rate", "respiratory rate"), "resp"),
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
    label: str | None  # the word right before it, as spelled
    measure: str | None  # what its label measures ("temp" for "T" and "Temperature")
    unit: WrittenUnit | None  # the unit written after it, if any
    bare_rate: tuple[str, ...]  # a rate written right after it with no unit ("100/hr")
    with_unit: Span  # the number and the unit written after it, in the note as typed
    typed_with_unit: str
    time: str | None  # the time word written right after it, by meaning ("hour" for "hrs")
    typed_with_time: str  # the number and that time word, as typed ("8 hrs")
    with_time: Span


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


def _label_before(text: str) -> str | None:
    """The word right before a number, given the text up to it."""
    match = _LABEL.search(text)
    return None if match is None else match.group(1).casefold()


def _measure_before(text: str) -> str | None:
    """What the label right before a number measures, given the text up to it.

    Two words are tried first ("heart rate"), then one. A label outside the table is its own
    measure, as spelled.
    """
    two = _TWO_WORD_LABEL.search(text)
    if two is not None:
        words = " ".join(two.group(1).casefold().split())
        if words in _MEASURES:
            return _MEASURES[words]
    label = _label_before(text)
    return None if label is None else _MEASURES.get(label, label)


def _note_numbers(raw: str, quote_spans: list[Span]) -> list[_NoteNumber]:
    """The numbers of the typed note that overlap a found quote, each compared whole.

    A quote that stops inside a number or its unit still brings in all of it; labels are read
    only inside the quote.
    """
    out: list[_NoteNumber] = []
    tokens = numbers_in(raw)
    for quote in quote_spans:
        for written, span in tokens:
            if span.start >= quote.end or span.end <= quote.start:
                continue
            unit = written_unit(raw, span)
            bare_rate, bare_end = bare_rate_end_after(raw, span)
            with_unit = Span(start=span.start, end=bare_end if unit is None else unit.end)
            before = raw[quote.start : span.start] if span.start >= quote.start else None
            time = time_after(raw, span)
            with_time = Span(start=span.start, end=span.end if time is None else time[1])
            out.append(
                _NoteNumber(
                    value=number_value(written),
                    text=written,
                    span=span,
                    label=None if before is None else _label_before(before),
                    measure=None if before is None else _measure_before(before),
                    unit=unit,
                    bare_rate=() if unit is not None else bare_rate,
                    with_unit=with_unit,
                    typed_with_unit=raw[with_unit.start : with_unit.end],
                    time=None if time is None else time[0],
                    typed_with_time=raw[with_time.start : with_time.end],
                    with_time=with_time,
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
    for written, span in numbers_in(text):
        value = number_value(written)
        before = text[: span.start]
        # A label the quotes use for some number says which of their numbers this one must be,
        # whether the line spells it as they do or names the same measure another way ("Temp" for
        # "T", "heart rate" for "HR"): a value they give that measure under another label is a
        # swap. The units are compared with the numbers of the label as spelled, as before.
        label = _label_before(before)
        measure = _measure_before(before)
        labelled = [n for n in note_numbers if label is not None and n.label == label]
        measured = [n for n in note_numbers if measure is not None and n.measure == measure]
        same_value = [n for n in labelled or note_numbers if n.value == value]
        swapped = bool(measured) and all(n.value != value for n in measured)
        if not same_value or swapped:
            paired = labelled[0] if labelled and not same_value else next(iter(measured), None)
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
        drafted = written_unit(text, span)
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
            rate, end = bare_rate_end_after(text, span)
            dropped = bool(rate) and bool(rates) and rate not in rates
        else:
            end = drafted.end
            dropped = bool(rated) and drafted.compared is not None and not drafted.rate
        if not dropped and (
            drafted is None or any(_same_unit(drafted, n, units) for n in candidates)
        ):
            continue
        line_rate = bare_rate_end_after(text, span)[0] if drafted is None else drafted.rate
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
    out.extend(_frequency_mismatches(text, quote_texts, out))
    return sorted(out, key=lambda mismatch: mismatch.draft_span.start)


def _frequency_mismatches(
    text: str, quote_texts: list[str], found: list[NumberMismatch]
) -> list[NumberMismatch]:
    """The frequencies of the line that no found quote gives by meaning.

    A frequency that overlaps a mismatch the line already has ("twice" missing from the quotes,
    the "3" of "3 times a day") is not flagged again.
    """
    in_the_quotes = {
        frequency.meaning for quote in quote_texts for frequency in frequencies_in(quote)
    }
    return [
        NumberMismatch(
            kind=MismatchKind.VALUE,
            draft_text=frequency.text,
            draft_span=frequency.span,
            note_text=None,
            note_span=None,
        )
        for frequency in frequencies_in(text)
        if frequency.meaning not in in_the_quotes
        and not any(
            frequency.span.start < mismatch.draft_span.end
            and mismatch.draft_span.start < frequency.span.end
            for mismatch in found
        )
    ]
