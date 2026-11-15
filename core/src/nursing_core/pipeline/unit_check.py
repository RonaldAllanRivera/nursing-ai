"""Numbers and the units written right after them.

A number is read with its context: ".5" is 0.5, a number with thousands separators ("5,000") is
one number, numbers joined by "/" ("1/2", "90/60") are one group, a vulgar fraction ("½") is the
group it stands for, and a whole number with a proper fraction ("1½", "1 1/2", "1 and ½",
"1 & 1/2") is one mixed number. Whole digits after a letter and followed by letters that are not a
unit ("D5LR", "q4h") belong to a word; "HR121bpm" and "BT37.9C" keep their numbers. The code never
converts units. It only reads the few spellings below, so a unit the nurse didn't write can be
told apart from one she did.
"""

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal

from nursing_core.domain.notes import Span
from nursing_core.domain.units import Ucum

_FRACTION_SLASH = chr(0x2044)
_VULGAR_FRACTIONS = "".join(
    chr(code)
    for code in range(0xA0, 0x2200)
    if re.fullmatch(rf"\d+{_FRACTION_SLASH}\d+", unicodedata.normalize("NFKC", chr(code)))
)
_SLASHES = f"/{_FRACTION_SLASH}\uff0f"  # a slash, the fraction slash and the full-width slash
# Comma thousands separators ("5,000", "1,000.5") make one number, its value without the commas.
_THOUSANDS = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?(?!\d)"
_PART = rf"{_THOUSANDS}|\d+(?:\.\d+)?|(?<!\d)\.\d+|[{_VULGAR_FRACTIONS}]"
_GROUP = rf"(?:{_PART})(?:[{_SLASHES}](?:{_PART}))*"
# A whole number then a vulgar fraction ("1½", "1 ½", "1 and ½"), or then spaces, " and " or " & "
# and a proper n/m fraction ("1 1/2", "1 and 1/2"). A space may be a tab or a no-break space.
_JOIN = r"(?i:\s+(?:and|&)\s+|[ \t\u00a0]+)"
_MIXED = rf"\d+(?:{_JOIN}?[{_VULGAR_FRACTIONS}]|{_JOIN}\d+[{_SLASHES}]\d+)"
_NUMBER = re.compile(rf"(?P<mixed>{_MIXED})|{_GROUP}")
_MIXED_PARTS = re.compile(
    rf"(\d+)(?:{_JOIN}?([{_VULGAR_FRACTIONS}])|{_JOIN}(\d+)[{_SLASHES}](\d+))"
)
_WHOLE_NUMBER = re.compile(r"\d+")
_LETTERS = re.compile(r"[^\W\d_]+")
_WORD = re.compile(r"[^\W_]+")
_NUMBER_WORDS = frozenset(
    {"one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "half", "twice"}
)

# Longest first, so "lbs" is tried before "lb". These short spellings are read in the case shown;
# the degree sign and the word spellings are read apart (see _read_unit).
_ALIASES: tuple[tuple[str, Ucum], ...] = (
    ("lbs", Ucum.LB),
    ("kgs", Ucum.KG),
    ("mL", Ucum.ML),
    ("ml", Ucum.ML),
    ("cc", Ucum.ML),
    ("lb", Ucum.LB),
    ("kg", Ucum.KG),
    ("F", Ucum.DEG_F),
    ("C", Ucum.CEL),
)
_DEGREES = r"(?:deg(?:rees?)?[ \t]*)"
# Word spellings, read in any case: "degrees Fahrenheit", "deg F", "degF", "Celsius", "pounds".
_WORD_ALIASES: tuple[tuple[re.Pattern[str], Ucum], ...] = (
    (re.compile(rf"{_DEGREES}?fahrenheit|{_DEGREES}f", re.IGNORECASE), Ucum.DEG_F),
    (re.compile(rf"{_DEGREES}?celsius|{_DEGREES}c", re.IGNORECASE), Ucum.CEL),
    (re.compile(r"kilograms?", re.IGNORECASE), Ucum.KG),
    (re.compile(r"pounds?", re.IGNORECASE), Ucum.LB),
)
_DEGREE_UNITS = {"F": Ucum.DEG_F, "C": Ucum.CEL}
# masculine ordinal, ring above, superscript zero
_DEGREE_LOOKALIKES = {"\u00ba": "\u00b0", "\u02da": "\u00b0", "\u2070": "\u00b0"}
_LOOKALIKE_TABLE = str.maketrans(_DEGREE_LOOKALIKES)
# Dose and volume units compared by spelling when a line and its note both write one after the
# same value, in any case. Spellings of one unit share a key.
_COMPARED_UNITS = {
    "mg": "mg",
    "mcg": "mcg",
    "\u03bcg": "mcg",  # "µg" after folding
    "ug": "mcg",
    "g": "g",
    "gm": "g",
    "units": "units",
    "unit": "units",
    "u": "units",
    "iu": "iu",
    "meq": "meq",
    "mmol": "mmol",
    "l": "l",
    "ml": "ml",
    "cc": "ml",
}
# The unit spellings the code knows, folded. A letter run right after whole digits that is one of
# them ("HR121bpm") leaves the digits a number, and a note number followed by one has a unit.
_UNIT_SPELLINGS = frozenset(
    {alias.casefold() for alias, _ in _ALIASES}
    | set(_COMPARED_UNITS)
    | {"bpm", "cpm", "mmhg", "lpm", "gtts", "kcal", "cm", "mm"}
    | {"degf", "degc", "fahrenheit", "celsius", "kilogram", "kilograms", "pound", "pounds"}
)
type NumberValue = tuple[str | Decimal, ...]
_WINDOW = 24  # how many typed characters after a number are read for its unit


@dataclass(frozen=True, slots=True)
class WrittenUnit:
    """The unit written right after a number."""

    unit: Ucum | None  # the unit the alias table reads, if it reads one
    compared: str | None  # the dose or volume unit compared by spelling, if one is written
    end: int  # where the unit ends in the text


def numbers_in(text: str) -> list[tuple[str, Span]]:
    """Every number, "/" group or mixed number as written, with its span in `text`.

    Digits that are part of a word ("D5LR", "q4h") are skipped.
    """
    return _scan(text)[0]


def words_with_numbers(text: str) -> list[tuple[str, Span]]:
    """Words that carry a number that isn't read as one, with their spans in `text`.

    These are words with digits inside ("q4h", "D5W", "HR121bpmRR20") and the number words one to
    ten, "half" and "twice". They can't be compared by value, only as whole words.
    """
    in_words = _scan(text)[1]
    out: list[tuple[str, Span]] = []
    for word in _WORD.finditer(text):
        start, end = word.span()
        if word.group().casefold() in _NUMBER_WORDS or any(start <= i < end for i in in_words):
            out.append((word.group(), Span(start=start, end=end)))
    return out


def _scan(text: str) -> tuple[list[tuple[str, Span]], list[int]]:
    """The numbers in `text`, and where each run of digits that belongs to a word starts."""
    numbers: list[tuple[str, Span]] = []
    in_words: list[int] = []
    position = 0
    while match := _NUMBER.search(text, position):
        start, end = match.span()
        if match.group("mixed") and not _proper_mixed(match.group()):
            end = start + next(i for i, char in enumerate(match.group()) if not char.isdecimal())
        position = end
        if _in_a_word(text, start, end):
            in_words.append(start)
        else:
            numbers.append((text[start:end], Span(start=start, end=end)))
    return numbers, in_words


def _proper_mixed(token: str) -> bool:
    parts = _MIXED_PARTS.fullmatch(token)
    return parts is not None and (parts.group(2) is not None or int(parts[3]) < int(parts[4]))


def _in_a_word(text: str, start: int, end: int) -> bool:
    """Whole digits after a letter and followed by letters that aren't a unit belong to a word."""
    if start == 0 or not text[start - 1].isalpha() or not _WHOLE_NUMBER.fullmatch(text[start:end]):
        return False
    letters = _LETTERS.match(text[end : end + _WINDOW].translate(_LOOKALIKE_TABLE))
    return letters is not None and letters.group().casefold() not in _UNIT_SPELLINGS


def number_value(token: str) -> NumberValue:
    """What a token stands for, so "½", "1/2" and "1/2.0" are equal and "1½" equals "1 1/2".

    A mixed number is kept apart from a plain group or number of the same size.
    """
    mixed = _MIXED_PARTS.fullmatch(token)
    if mixed:
        fraction = number_value(mixed[2]) if mixed[2] else (Decimal(mixed[3]), Decimal(mixed[4]))
        return ("mixed", Decimal(mixed[1]), *fraction)
    values: list[Decimal] = []
    for part in re.split("[/\uff0f]", token):
        folded = unicodedata.normalize("NFKC", part).replace(",", "")
        values.extend(Decimal(piece) for piece in folded.split(_FRACTION_SLASH))
    return tuple(values)


def unit_after(text: str, number_span: Span) -> Ucum | None:
    found = unit_end_after(text, number_span)
    return None if found is None else found[0]


def unit_end_after(text: str, number_span: Span) -> tuple[Ucum, int] | None:
    """The unit written after a number and where it ends in `text`, or None when there is none."""
    folded, origin = _fold_after(text, number_span.end)
    read = _read_unit(folded)
    if read is None:
        return None
    unit, stop = read
    return unit, origin[stop - 1] + 1


def written_unit(text: str, number_span: Span) -> WrittenUnit | None:
    """The unit written right after a number, or None when there is none.

    Any unit spelling the code knows counts, even one the alias table doesn't read ("1L", "500 mg").
    """
    read = unit_end_after(text, number_span)
    spelled = _spelling_after(text, number_span)
    if read is None and spelled is None:
        return None
    unit, unit_end = (None, number_span.end) if read is None else read
    spelling, spelling_end = (None, number_span.end) if spelled is None else spelled
    return WrittenUnit(
        unit=unit,
        compared=None if spelling is None else _COMPARED_UNITS.get(spelling),
        end=max(unit_end, spelling_end),
    )


def _spelling_after(text: str, number_span: Span) -> tuple[str, int] | None:
    """A known unit spelling written right after a number, folded, and where it ends in `text`."""
    folded, origin = _fold_after(text, number_span.end)
    letters = _LETTERS.match(folded, len(folded) - len(folded.lstrip(" \t")))
    if letters is None or not _word_ends(folded, letters.end()):
        return None
    spelling = letters.group().casefold()
    if spelling not in _UNIT_SPELLINGS:
        return None
    return spelling, origin[letters.end() - 1] + 1


def _fold_after(text: str, start: int) -> tuple[str, list[int]]:
    """The typed characters after a number, folded, and the typed index behind each one."""
    folded: list[str] = []
    origin: list[int] = []
    for index in range(start, min(len(text), start + _WINDOW)):
        char = _DEGREE_LOOKALIKES.get(text[index], text[index])
        for part in unicodedata.normalize("NFKC", char):
            folded.append(part)
            origin.append(index)
    return "".join(folded), origin


def _read_unit(folded: str) -> tuple[Ucum, int] | None:
    """The unit at the start of the folded characters after a number, and where it ends."""
    if folded.startswith("#"):
        return (Ucum.LB, 1) if _word_ends(folded, 1) else None
    start = len(folded) - len(folded.lstrip(" \t"))
    if folded.startswith("°", start):
        letter = start + 1 + len(folded[start + 1 :]) - len(folded[start + 1 :].lstrip(" "))
        unit = _DEGREE_UNITS.get(folded[letter : letter + 1])
        return (unit, letter + 1) if unit and _word_ends(folded, letter + 1) else None
    for pattern, unit in _WORD_ALIASES:
        word = pattern.match(folded, start)
        if word and _word_ends(folded, word.end()):
            return unit, word.end()
    for alias, unit in _ALIASES:
        if folded.startswith(alias, start) and _word_ends(folded, start + len(alias)):
            return unit, start + len(alias)
    return None


def _word_ends(folded: str, stop: int) -> bool:
    """A unit isn't followed by a letter, a digit or a slash ("c/o", "2 Foley", "100 mL/hr")."""
    following = folded[stop : stop + 1]
    return not (following.isalnum() or following == "/")
