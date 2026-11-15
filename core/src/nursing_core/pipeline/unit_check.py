"""Numbers and the units written right after them.

The code never converts units. It only reads the few spellings below, exactly as listed, so a
unit the nurse didn't write can be told apart from one she did.
"""

import re

from nursing_core.domain.notes import Span
from nursing_core.domain.units import Ucum

_NUMBER = re.compile(r"\d+(?:\.\d+)?")

# Longest first, so "lbs" is tried before "lb" and "°F" before "F".
_ALIASES: tuple[tuple[str, Ucum], ...] = (
    ("degF", Ucum.DEG_F),
    ("lbs", Ucum.LB),
    ("°F", Ucum.DEG_F),
    ("°C", Ucum.CEL),
    ("mL", Ucum.ML),
    ("ml", Ucum.ML),
    ("cc", Ucum.ML),
    ("lb", Ucum.LB),
    ("kg", Ucum.KG),
    ("F", Ucum.DEG_F),
    ("C", Ucum.CEL),
)
_NOT_AFTER_UNIT = re.compile(r"[^\W_]|/")  # a letter or digit, or a slash: the word goes on


def numbers_in(text: str) -> list[tuple[str, Span]]:
    """Every number as written, with its span in `text`."""
    return [(m.group(), Span(start=m.start(), end=m.end())) for m in _NUMBER.finditer(text)]


def unit_after(text: str, number_span: Span) -> Ucum | None:
    found = unit_end_after(text, number_span)
    return None if found is None else found[0]


def unit_end_after(text: str, number_span: Span) -> tuple[Ucum, int] | None:
    """The unit written after a number and where it ends, or None when there is none."""
    end = number_span.end
    if text.startswith("#", end):
        return Ucum.LB, end + 1
    start = end
    while start < len(text) and text[start] in " \t":
        start += 1
    for alias, unit in _ALIASES:
        stop = start + len(alias)
        if text.startswith(alias, start) and not _NOT_AFTER_UNIT.match(text[stop : stop + 1]):
            return unit, stop
    return None
