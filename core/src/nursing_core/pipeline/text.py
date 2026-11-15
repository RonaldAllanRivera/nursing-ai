"""Normalised text matching that maps every match back to the characters the nurse typed."""

import unicodedata
from dataclasses import dataclass

from nursing_core.domain.notes import Span

_STRAIGHT_QUOTES = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u201f": '"',
    }
)


@dataclass(frozen=True, slots=True)
class MatchText:
    text: str  # the normalised text
    origin: list[int]  # origin[i] = index in `raw` of the code point that produced text[i]
    raw: str  # the text exactly as typed


def prepare(raw: str) -> MatchText:
    """Normalise one code point at a time so each result character has one raw origin.

    Known limit: a precomposed letter ("\u00f1") and its decomposed form don't match each other.
    That error is towards "not found", which is safe. NFKC also folds "\u00bd" to "1\u20442" and
    "10\u00b3" to "103" in the matching text, so numbers are read from the typed text, never from
    this one.
    """
    chars: list[str] = []
    origin: list[int] = []
    in_space_run = False
    for index, code_point in enumerate(raw):
        folded = unicodedata.normalize("NFKC", code_point).casefold().translate(_STRAIGHT_QUOTES)
        for char in folded:
            if char.isspace():
                if not in_space_run:
                    chars.append(" ")
                    origin.append(index)
                in_space_run = True
            else:
                chars.append(char)
                origin.append(index)
                in_space_run = False
    return MatchText(text="".join(chars), origin=origin, raw=raw)


def find_span(note: MatchText, quote: str) -> Span | None:
    """Where the quote first appears in the note, as a span of the note's raw text."""
    needle = prepare(quote).text.strip()
    if not needle:
        return None
    start = note.text.find(needle)
    while start >= 0:
        end = start + len(needle)
        if not _inside_longer_word(note.text, start, end):
            return Span(start=note.origin[start], end=note.origin[end - 1] + 1)
        start = note.text.find(needle, start + 1)
    return None


_HYPHENS = ("-", "\u2010")  # "\u2011" is folded to "\u2010" by prepare


def _at(text: str, index: int) -> str:
    return text[index] if 0 <= index < len(text) else ""


def _inside_longer_word(text: str, start: int, end: int) -> bool:
    """True when text[start:end] is only part of a word, a hyphenated word or a number.

    A combining mark on a letter is part of that letter's word in every rule here, inside the
    quote and out, because every letter test goes through _is_letter.
    """
    before, after = _at(text, start - 1), _at(text, end)
    if _run_on(text, start - 1) or _run_on(text, end - 1):
        return True
    return _cut_at_hyphen(text, start, end, before, after) or _cut_inside_decimal(
        text, start, end, before, after
    )


def _cut_at_hyphen(text: str, start: int, end: int, before: str, after: str) -> bool:
    first, last = text[start], text[end - 1]
    if first in _HYPHENS and _is_letter(text, start - 1):
        return True
    if last in _HYPHENS and _is_letter(text, end):
        return True
    if _is_letter(text, start) and before in _HYPHENS and _is_letter(text, start - 2):
        return True
    return _is_letter(text, end - 1) and after in _HYPHENS and _is_letter(text, end + 1)


def _cut_inside_decimal(text: str, start: int, end: int, before: str, after: str) -> bool:
    first, last = text[start], text[end - 1]
    if first.isdigit() and before == ".":
        return True
    if first == "." and before.isdigit() and _at(text, start + 1).isdigit():
        return True
    if last == "." and _at(text, end - 2).isdigit() and after.isdigit():
        return True
    return last.isdigit() and after == "." and _at(text, end + 1).isdigit()


def _is_mark(char: str) -> bool:
    return bool(char) and unicodedata.category(char).startswith("M")


def _is_letter(text: str, index: int) -> bool:
    """True when text[index] is a letter, or a combining mark attached to a letter.

    A mark attaches to the character before its run of marks. A mark on anything else, such as
    the variation selector that draws a symbol as an emoji, is not part of a word.
    """
    while _is_mark(_at(text, index)):
        index -= 1
    return _at(text, index).isalpha()


def _run_on(text: str, left: int) -> bool:
    """True when text[left] and the next character are both letters or both digits."""
    right = left + 1
    return (_is_letter(text, left) and _is_letter(text, right)) or (
        _at(text, left).isdigit() and _at(text, right).isdigit()
    )
