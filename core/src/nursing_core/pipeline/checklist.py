"""Things the chart says belong in this shift's notes that the notes don't mention yet."""

import re
import unicodedata
from bisect import bisect_right
from collections.abc import Iterable, Sequence
from datetime import datetime

from nursing_core.domain.notes import ChecklistItem, ChecklistRule, Span
from nursing_core.domain.patient import PatientContext
from nursing_core.pipeline.checklist_words import DEFAULT_WORDS, ChecklistWords
from nursing_core.pipeline.text import MatchText, prepare


def _find_all(note: MatchText, phrase: str) -> list[Span]:
    """Whole-word matches of the phrase in the note, as spans of the note as typed."""
    needle = prepare(phrase).text.strip()
    if not needle:
        return []
    pattern = re.compile(rf"(?<!\w){re.escape(needle)}(?!\w)")
    return [
        Span(start=note.origin[m.start()], end=note.origin[m.end() - 1] + 1)
        for m in pattern.finditer(note.text)
        if not _touches_a_mark(note.text, m.start(), m.end())
    ]


def _touches_a_mark(text: str, start: int, end: int) -> bool:
    """A combining mark joins the match to a longer word only when it sits on a letter.

    A mark before the match counts when its run of marks attaches to a letter; a mark after
    it counts when the match ends in a letter. An emoji's variation selector is neither.
    """
    if end < len(text) and _is_mark(text[end]) and text[end - 1].isalpha():
        return True
    index = start - 1
    while index >= 0 and _is_mark(text[index]):
        index -= 1
    return index < start - 1 and index >= 0 and text[index].isalpha()


def _is_mark(char: str) -> bool:
    return unicodedata.category(char).startswith("M")


def _find_any(note: MatchText, phrases: Iterable[str]) -> list[Span]:
    return [span for phrase in phrases for span in _find_all(note, phrase)]


_LINE_BREAKS = frozenset("\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029")
_ALWAYS_END = frozenset(";?!:\u3002\u3001\u2014\u2192")
_SPACED = frozenset("/|\u2022")
_CLOSERS = frozenset("\"')]}\u201d\u2019\u300d\u300f")
_EN_DASH = "\u2013"


def _clause_ends(raw: str) -> list[int]:
    """Offsets in the typed text of the characters that end a clause, in ascending order.

    A clause ends at a line break; at ; ? ! : , and their full-width forms, except a "," between
    digits ("5,000"); at an ellipsis, an em dash or an arrow ("→"); at an en dash, except
    between digits (a range); at a run of hyphens with whitespace on both sides (" - ", " -- ",
    " -> "); and at a slash, bar or bullet with whitespace on both sides.

    A "." ends a clause when whitespace, the end or a letter comes next, right after it or after
    a run of closing quotes and brackets ("due.)"). It doesn't when a digit comes next ("0.5"),
    nor before a letter when exactly one letter that doesn't follow a digit comes right before it
    ("p.o", "c.given"; "q8h.Given" still ends one). The last "." of a dotted abbreviation
    ("p.o.") ends a clause only when whitespace and then an upper-case letter come next.
    Characters are judged after the same per-code-point folding the matcher uses.
    """
    folds = [unicodedata.normalize("NFKC", code_point) for code_point in raw]
    return [index for index in range(len(raw)) if _ends_clause(raw, folds, index)]


def _ends_clause(raw: str, folds: list[str], index: int) -> bool:
    fold = folds[index]
    if raw[index] in _LINE_BREAKS or fold[-1:] in _ALWAYS_END or raw[index] in _ALWAYS_END:
        return True
    if fold == ",":
        return not (_is_digit(folds, index - 1) and _is_digit(folds, index + 1))
    if fold == _EN_DASH:
        return not (_is_digit(folds, index - 1) and _is_digit(folds, index + 1))
    if fold in _SPACED:
        return _is_space(folds, index - 1) and _is_space(folds, index + 1)
    if fold == "-":
        return _ends_spaced_hyphen(folds, index)
    if fold == ".":
        return _ends_sentence(raw, folds, index)
    return fold.endswith(".")


def _ends_spaced_hyphen(folds: list[str], index: int) -> bool:
    """A hyphen run with whitespace on both sides, or a spaced arrow " -> "."""
    if not _is_space(folds, index - 1):
        return False
    after = index + 1
    while after < len(folds) and folds[after] == "-":
        after += 1
    if after < len(folds) and folds[after] == ">":
        after += 1
    return _is_space(folds, after)


def _is_digit(folds: list[str], index: int) -> bool:
    return 0 <= index < len(folds) and folds[index].isdigit()


def _is_space(folds: list[str], index: int) -> bool:
    return 0 <= index < len(folds) and folds[index].isspace()


def _is_letter(folds: list[str], index: int) -> bool:
    return 0 <= index < len(folds) and folds[index].isalpha()


def _ends_sentence(raw: str, folds: list[str], index: int) -> bool:
    """Whether the "." at this offset ends a sentence rather than a number or abbreviation."""
    after = index + 1
    while after < len(folds) and folds[after] in _CLOSERS:
        after += 1
    closed = after > index + 1
    if after >= len(folds) or _is_space(folds, after):
        if closed or not _ends_abbreviation(folds, index):
            return True
        return _upper_case_follows(raw, after)
    if not _is_letter(folds, after):
        return False
    one_letter = _is_letter(folds, index - 1) and not (
        _is_letter(folds, index - 2) or _is_digit(folds, index - 2)
    )
    return closed or not one_letter


def _ends_abbreviation(folds: list[str], index: int) -> bool:
    """A single letter, itself right after a "." ("p.o."), then this ".": an abbreviation."""
    return _is_letter(folds, index - 1) and index >= 2 and folds[index - 2] == "."


def _upper_case_follows(raw: str, index: int) -> bool:
    rest = raw[index:].lstrip()
    return rest[:1].isupper()


def _clause_number(ends: list[int], offset: int) -> int:
    return bisect_right(ends, offset)


def _earliest(spans: list[Span]) -> Span | None:
    return min(spans, key=lambda s: (s.start, s.start - s.end), default=None)


def _recorded_in_a_clause(
    note: MatchText, ends: list[int], aliases: list[str], words: list[str], not_yet: list[str]
) -> bool:
    """Whether an action word shares a clause with the medicine, with no word before it in that
    clause that says it hasn't happened yet ("not given", "to be given", "hindi pa binigay")."""
    mentioned = {_clause_number(ends, s.start) for s in _find_any(note, aliases)}
    negations = _find_any(note, not_yet)
    for action in _find_any(note, words):
        clause = _clause_number(ends, action.start)
        if clause in mentioned and not any(
            _clause_number(ends, n.start) == clause and n.end <= action.start for n in negations
        ):
            return True
    return False


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
    clause_ends = [_clause_ends(note.raw) for note in notes]

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
            _recorded_in_a_clause(note, ends, medicine.aliases, action_words, words.not_yet)
            for note, ends in zip(notes, clause_ends, strict=True)
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
