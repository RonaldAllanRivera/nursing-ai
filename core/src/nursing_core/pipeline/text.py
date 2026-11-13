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
    That errs towards "not found", which is safe.
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
        before = note.text[start - 1] if start > 0 else ""
        after = note.text[end] if end < len(note.text) else ""
        if not (_run_on(before, needle[0]) or _run_on(needle[-1], after)):
            return Span(start=note.origin[start], end=note.origin[end - 1] + 1)
        start = note.text.find(needle, start + 1)
    return None


def _run_on(left: str, right: str) -> bool:
    """True when two neighbouring characters are both letters or both digits (one word/number)."""
    return (left.isalpha() and right.isalpha()) or (left.isdigit() and right.isdigit())
