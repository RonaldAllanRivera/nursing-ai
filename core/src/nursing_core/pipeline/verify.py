"""Deciding each draft line's status from its quotes, numbers and units.

Numbers, units and labels are read only from the typed slices of the note that the found quotes
cover, never from the normalised matching text, so a character the matcher folds (a typed "½",
say) can't make a number appear that the nurse didn't write.
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
from nursing_core.pipeline.unit_check import NumberValue, number_value, numbers_in, unit_end_after

# The word right before a number; spaces and one ":" or "=" may sit between.
_LABEL = re.compile(r"(?<!\w)([^\W\d_][^\W_]*)[ \t]*[:=]?[ \t]*$")

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
    label: str | None
    unit: Ucum | None
    with_unit: Span  # the number and the unit written after it, in the note as typed
    typed_with_unit: str


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
    mismatches = _mismatches(text, note_numbers, units)
    if mismatches:
        return LineStatus.NUMBER_MISMATCH, mismatches
    return (LineStatus.SUMMARY if own_wording else LineStatus.SOURCE_FOUND), []


def _label_before(text: str) -> str | None:
    """The word right before a number, given the text up to it."""
    match = _LABEL.search(text)
    return None if match is None else match.group(1).casefold()


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
            unit = unit_end_after(raw, span)
            with_unit = Span(start=span.start, end=span.end if unit is None else unit[1])
            label = (
                _label_before(raw[quote.start : span.start]) if span.start >= quote.start else None
            )
            out.append(
                _NoteNumber(
                    value=number_value(written),
                    text=written,
                    span=span,
                    label=label,
                    unit=None if unit is None else unit[0],
                    with_unit=with_unit,
                    typed_with_unit=raw[with_unit.start : with_unit.end],
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


def _mismatches(
    text: str, note_numbers: list[_NoteNumber], units: UnitDefaults
) -> list[NumberMismatch]:
    out: list[NumberMismatch] = []
    for written, span in numbers_in(text):
        same_value = [n for n in note_numbers if n.value == number_value(written)]
        if not same_value:
            label = _label_before(text[: span.start])
            paired = next((n for n in note_numbers if label and n.label == label), None)
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
        drafted = unit_end_after(text, span)
        if drafted is None:
            continue
        unit, unit_end = drafted
        default = default_unit(unit, units)
        if any(n.unit == unit or (n.unit is None and default == unit) for n in same_value):
            continue
        first = same_value[0]
        out.append(
            NumberMismatch(
                kind=MismatchKind.UNIT,
                draft_text=text[span.start : unit_end],
                draft_span=Span(start=span.start, end=unit_end),
                note_text=first.typed_with_unit,
                note_span=first.with_unit,
            )
        )
    return out
