"""Numbers and the units written right after them.

A number is read with its context: ".5" is 0.5, numbers joined by "/" ("1/2", "90/60") are one
group, a vulgar fraction ("½") is the group it stands for, and digits with a letter on both sides
("D5LR", "q4h") belong to a word. The code never converts units. It only reads the few spellings
below, so a unit the nurse didn't write can be told apart from one she did.
"""

import re
import unicodedata
from decimal import Decimal

from nursing_core.domain.notes import Span
from nursing_core.domain.units import Ucum

_FRACTION_SLASH = chr(0x2044)
_VULGAR_FRACTIONS = "".join(
    chr(code)
    for code in range(0xA0, 0x2200)
    if re.fullmatch(rf"\d+{_FRACTION_SLASH}\d+", unicodedata.normalize("NFKC", chr(code)))
)
_PART = rf"\d+(?:\.\d+)?|(?<!\d)\.\d+|[{_VULGAR_FRACTIONS}]"
_NUMBER = re.compile(rf"(?:{_PART})(?:/(?:{_PART}))*")

# Longest first, so "lbs" is tried before "lb". The degree alias is read apart (see _read_unit).
_ALIASES: tuple[tuple[str, Ucum], ...] = (
    ("degF", Ucum.DEG_F),
    ("lbs", Ucum.LB),
    ("mL", Ucum.ML),
    ("ml", Ucum.ML),
    ("cc", Ucum.ML),
    ("lb", Ucum.LB),
    ("kg", Ucum.KG),
    ("F", Ucum.DEG_F),
    ("C", Ucum.CEL),
)
_DEGREE_UNITS = {"F": Ucum.DEG_F, "C": Ucum.CEL}
_DEGREE_LOOKALIKES = {"º": "°", "˚": "°"}  # masculine ordinal, ring above
_WINDOW = 24  # how many typed characters after a number are read for its unit


def numbers_in(text: str) -> list[tuple[str, Span]]:
    """Every number or "/" group as written, with its span in `text`; words' digits are skipped."""
    out: list[tuple[str, Span]] = []
    for match in _NUMBER.finditer(text):
        before = text[match.start() - 1 : match.start()] if match.start() else ""
        after = text[match.end() : match.end() + 1]
        if before.isalpha() and after.isalpha():
            continue
        out.append((match.group(), Span(start=match.start(), end=match.end())))
    return out


def number_value(token: str) -> tuple[Decimal, ...]:
    """The values of a token as written, in order, so "½", "1/2" and "1/2.0" are equal."""
    values: list[Decimal] = []
    for part in token.split("/"):
        folded = unicodedata.normalize("NFKC", part)
        values.extend(Decimal(piece) for piece in folded.split(_FRACTION_SLASH))
    return tuple(values)


def unit_after(text: str, number_span: Span) -> Ucum | None:
    found = unit_end_after(text, number_span)
    return None if found is None else found[0]


def unit_end_after(text: str, number_span: Span) -> tuple[Ucum, int] | None:
    """The unit written after a number and where it ends in `text`, or None when there is none."""
    start = number_span.end
    folded: list[str] = []
    origin: list[int] = []
    for index in range(start, min(len(text), start + _WINDOW)):
        char = _DEGREE_LOOKALIKES.get(text[index], text[index])
        for part in unicodedata.normalize("NFKC", char):
            folded.append(part)
            origin.append(index)
    read = _read_unit("".join(folded))
    if read is None:
        return None
    unit, stop = read
    return unit, origin[stop - 1] + 1


def _read_unit(folded: str) -> tuple[Ucum, int] | None:
    """The unit at the start of the folded characters after a number, and where it ends."""
    if folded.startswith("#"):
        return (Ucum.LB, 1) if _word_ends(folded, 1) else None
    start = len(folded) - len(folded.lstrip(" \t"))
    if folded.startswith("°", start):
        letter = start + 1 + len(folded[start + 1 :]) - len(folded[start + 1 :].lstrip(" "))
        unit = _DEGREE_UNITS.get(folded[letter : letter + 1])
        return (unit, letter + 1) if unit and _word_ends(folded, letter + 1) else None
    for alias, unit in _ALIASES:
        if folded.startswith(alias, start) and _word_ends(folded, start + len(alias)):
            return unit, start + len(alias)
    return None


def _word_ends(folded: str, stop: int) -> bool:
    """A unit isn't followed by a letter, a digit or a slash ("c/o", "2 Foley", "100 mL/hr")."""
    following = folded[stop : stop + 1]
    return not (following.isalnum() or following == "/")
