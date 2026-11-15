"""Things the chart says belong in this shift's notes that the notes don't mention yet."""

import re
from collections.abc import Iterable, Sequence
from datetime import datetime

from nursing_core.domain.notes import ChecklistItem, ChecklistRule, Span
from nursing_core.domain.patient import PatientContext
from nursing_core.pipeline.checklist_words import DEFAULT_WORDS, ChecklistWords
from nursing_core.pipeline.text import MatchText, prepare

# A sentence ends at a line break, at ";" and at "." followed by whitespace or the end of the
# note, so "0.5 mg" stays in one sentence.
_SENTENCE_END = re.compile(r"[\n\r\x0b\x0c\x1c-\x1e\x85\u2028\u2029;]|\.(?=\s|\Z)")


def _find_all(note: MatchText, phrase: str) -> list[Span]:
    """Whole-word matches of the phrase in the note, as spans of the note as typed."""
    needle = prepare(phrase).text.strip()
    if not needle:
        return []
    pattern = re.compile(rf"(?<!\w){re.escape(needle)}(?!\w)")
    return [
        Span(start=note.origin[m.start()], end=note.origin[m.end() - 1] + 1)
        for m in pattern.finditer(note.text)
    ]


def _find_any(note: MatchText, phrases: Iterable[str]) -> list[Span]:
    return [span for phrase in phrases for span in _find_all(note, phrase)]


def _sentence_number(raw: str, offset: int) -> int:
    return sum(1 for m in _SENTENCE_END.finditer(raw) if m.start() < offset)


def _earliest(spans: list[Span]) -> Span | None:
    return min(spans, key=lambda s: (s.start, s.start - s.end), default=None)


def _recorded_in_a_sentence(note: MatchText, aliases: list[str], words: list[str]) -> bool:
    mentioned = {_sentence_number(note.raw, s.start) for s in _find_any(note, aliases)}
    return any(_sentence_number(note.raw, s.start) in mentioned for s in _find_any(note, words))


def _item(
    rule: ChecklistRule, subject: str, missing: bool, current: MatchText, phrases: list[str]
) -> ChecklistItem:
    span = None if missing else _earliest(_find_any(current, phrases))
    return ChecklistItem(rule=rule, subject=subject, missing=missing, note_span=span)


def missing_items_checklist(
    context: PatientContext,
    shift_note_texts: Sequence[str],
    last_note_at: datetime,
    words: ChecklistWords = DEFAULT_WORDS,
) -> list[ChecklistItem]:
    """Checklist items for this shift. The last note is the one being drafted; never blocks."""
    if not shift_note_texts:
        raise ValueError("at least one note is needed")
    if last_note_at.tzinfo is None or last_note_at.utcoffset() is None:
        raise ValueError("last_note_at needs a timezone")
    notes = [prepare(text) for text in shift_note_texts]
    current = notes[-1]

    def mentioned(phrases: list[str]) -> bool:
        return any(_find_any(note, phrases) for note in notes)

    items: list[ChecklistItem] = []
    if context.allergies is None:
        items.append(
            ChecklistItem(
                rule=ChecklistRule.ALLERGIES, subject="Allergies", missing=True, note_span=None
            )
        )
    for tube in context.lines_tubes:
        items.append(
            _item(
                ChecklistRule.LINE_OR_TUBE,
                tube.description,
                not mentioned(tube.aliases),
                current,
                tube.aliases,
            )
        )
    due = [m for m in context.medicines_due if m.due_at <= last_note_at]
    action_words = [*words.given, *words.held, *words.refused]
    for medicine in sorted(due, key=lambda m: m.due_at):
        recorded = any(
            _recorded_in_a_sentence(note, medicine.aliases, action_words) for note in notes
        )
        items.append(
            _item(
                ChecklistRule.MEDICINE_DUE,
                f"{medicine.name} {medicine.dose} {medicine.route}",
                not recorded,
                current,
                medicine.aliases,
            )
        )
    for test in context.pending_tests:
        items.append(
            _item(
                ChecklistRule.PENDING_TEST,
                test.name,
                not mentioned(test.aliases),
                current,
                test.aliases,
            )
        )
    high = context.fall_risk is not None and context.fall_risk.high
    if high or mentioned(words.dizzy) or mentioned(words.confused):
        items.append(
            _item(
                ChecklistRule.FALL_RISK,
                "Fall risk",
                not mentioned(words.safety),
                current,
                words.safety,
            )
        )
    return items
