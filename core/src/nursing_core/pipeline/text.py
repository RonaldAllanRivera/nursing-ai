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
    A combining mark counts as part of its word, so a split-up letter is never cut in half.
    Both errors are towards "not found", which is safe.
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


def _at(text: str, index: int) -> str:
    return text[index] if 0 <= index < len(text) else ""


def _inside_longer_word(text: str, start: int, end: int) -> bool:
    """True when text[start:end] is only part of a word, a hyphenated word or a number."""
    first, last = text[start], text[end - 1]
    before, after = _at(text, start - 1), _at(text, end)
    if _is_mark(first) or (after and _is_mark(after)):
        return True
    if _run_on(before, first) or _run_on(last, after):
        return True
    if first.isalpha() and before == "-" and _at(text, start - 2).isalpha():
        return True
    if last.isalpha() and after == "-" and _at(text, end + 1).isalpha():
        return True
    if last.isdigit() and after == "." and _at(text, end + 1).isdigit():
        return True
    return first.isdigit() and before == "." and _at(text, start - 2).isdigit()


def _is_mark(char: str) -> bool:
    return unicodedata.category(char).startswith("M")


def _run_on(left: str, right: str) -> bool:
    """True when two neighbouring characters are both letters or both digits (one word/number)."""
    return (left.isalpha() and right.isalpha()) or (left.isdigit() and right.isdigit())
