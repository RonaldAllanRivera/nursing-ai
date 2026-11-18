"""Numbers and the units written right after them.

A number is read with its context: ".5" is 0.5, a number with thousands separators ("5,000") is
one number, numbers joined by "/" ("1/2", "90/60") are one group, a vulgar fraction ("½") is the
group it stands for, and a whole number with a proper fraction ("1½", "1 1/2", "1 and ½",
"1 & 1/2") is one mixed number. Whole digits after a letter and followed by letters that are not a
unit ("D5LR", "q4h") belong to a word; "HR121bpm" and "BT37.9C" keep their numbers. The code never
converts units. It only reads the few spellings below, so a unit the nurse didn't write can be
told apart from one she did.

A dose, volume or drop unit followed by "/" (spaces around it are fine) or "per" and a
denominator is a rate: "units/hr" and "units per hour" are units per hour, "mcg / kg / min" is mcg
per kg per minute, and "15 mg/week" is mg per week. Only a closed set counts as a denominator: a
time word (h, hr, hrs, hour, hours, min, mins, minute, minutes, d, day, days, wk, wks, week,
weeks, mo, mos, month, months, shift, shifts; "m" is minute after a unit, "L/m"), kg, kgs,
kilogram or kilograms, or a volume (ml, cc, milliliter, millilitre, dl, deciliter, decilitre, l,
liter, litre, with their plurals). Each is kept by meaning ("h",
"hr" and "hours" are one) and must be a whole word ("1L/D5LR" has no rate). Any other word ends
the unit with no rate ("500 mg/tab", "5 mg per NGT"), and so does a digit ("1L/8hrs",
"1 L / 8 hrs"). A rate is read whole when it fits in the 64 characters after the unit (after the
number, for a rate written right after a number: "100/hr"), as "5 mcg per kilograms per minute"
does, and the word the read ends in is finished; a rate starting after more than that is not read.
A "/" then the spelling "hr" and a number of two or three digits on the same line ("5 units / HR
88", "HR: 88", "HR=88", "HR - 88", "HR of 88", "HR 88bpm") may be per hour or a separator before a
heart rate: the rate is then unsure. It equals only itself, so a line that repeats the same
"/ HR 88" form passes, and a line that uses that number with a unit, with or without a rate, is a
mismatch. Any other hour spelling or number after it ("units/hr 0800", "mL/hr 2L", "units/h 88",
"units/hr 10:30") is the rate, and so is a number followed by a dose, volume or weight unit of two
letters or more ("units/hr = 10 mL/hr"). A single letter or "drop" after the number is read as a
word ("HR 88 L radial", "HR 88 u/a", "HR 88 drops to 60"), and so is "CC:" (a chief complaint):
the rate stays unsure.
Whitespace inside a rate includes a line break between "5 mg/" and "hr".
A concentration is a unit with its volume as the denominator: "g/dL", "mg/dL", "g/L", "mmol/L" and
"mEq/L" are each kept whole, so none equals another, a bare unit, or a rate per hour. "g/L" and
"u/L" are not shorthand.
A unit that takes no rate is read as written ("37.8C/HR 110"). A one-letter unit, "/" and one more
letter is clinical shorthand, not a unit ("c/o", "f/u", "u/a"), except when the unit is u, l or g
and the letter is h, d or m ("u/h", "L/m", "g/d"), which are rates.
"lpm" is litres per minute.
An ounce ("oz", "ozs", "ounce", "ounces", or "fl" or "fluid" then one of those past a "." and
spaces or a line break: "fl oz", "fl. oz", "fluid ounces"; in any case) is a unit of its own, kept
by spelling like the others: it is never mL, cc or L, a note number written with no unit never
stands for one, and nothing converts it, so "8 oz" is not "240 mL". It reads a rate like any
volume unit ("8 oz/hr"). "fl" or "fluid" alone is no unit.
A time word written right after a number with no unit between ("2 hours", "x 8 hrs", "20mins") is
read by meaning: hour, minute, day or week, from the same spellings as the denominators but for the
one-letter "m" and "d".
A frequency is read by meaning, in any case, each word whole, words separated by spaces, a line
break or a hyphen ("once-a-day"); the longest reading wins, left to right, so "once daily" is one
frequency and not "daily" inside it. One list of periods serves every spelling: day, week, month,
hour, night and shift. "daily", "every day", "everyday", "each day", "once a day", "once per day"
and "once daily" are one a day, and the same for each other period ("hourly", "nightly", "every
shift", "each night", "once an hour"). "every other day" (or any period) is its own meaning, not
"daily". A count is "twice" or "thrice", or a number (digits, read by value so "3" and "3.0" are
one, or a number word from two to ten) before "times" or "x". It is followed by an adverb
("daily", "nightly"), by "everyday", by "a", "an", "per", "every", "each" or "every other" and a
period, or by "/" and a period (spaces around the "/" are fine): "twice a day", "twice daily",
"2 times every day", "2 times everyday", "2x daily", "2x/day" and "2 times / day" are two a day,
"2 times every night" is two a night, "twice each shift" is two a shift, "2 times every other day"
is its own counted meaning, and "3 times a week" is not "3 times a day". "per" and a period is a
frequency only after "once" or a count, and "/" and a period only after a count, so "once/day" is
not read; otherwise neither is a frequency ("15 mg per day" and "15 mg/day" are rates). With no
"once" or count before it, "a" or "an" and a period is a frequency only right after a dose,
volume or drop unit written with no rate, and then is one per that period: "15 mg a day" is one a
day, while "fever for a day" has no frequency. That reading takes day, week, month, night and
shift but not hour ("1000 units an hour" has no frequency, as it is a rate in practice), and
never a period followed, past spaces or a line break, by the whole word ago, before, prior,
earlier, early, later or late: "15 mg a day ago" and "1 L a night before" say when, not how
often. The abbreviations (OD, QD, BID, TID, QID, QOD, HS, PRN, STAT) each mean only their own
spelling: "OD" is also the right eye, so it is never "daily". "once" alone is no frequency
("vomited once").
"""

import re
import unicodedata
from bisect import bisect_right
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
# An ounce spelling after "fl" or "fluid", past a "." and spaces or a line break: "fl. oz",
# "fluid ounces".
_FLUID_OUNCE = re.compile(r"\.?\s*(?:ozs?|ounces?)", re.IGNORECASE)
_NUMBER_WORDS = frozenset(
    {"one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "half", "twice"}
)
_ABBREVIATIONS = ("od", "qd", "bid", "tid", "qid", "qod", "hs", "prn", "stat")
_ADVERBS = {
    "daily": "day",
    "weekly": "week",
    "monthly": "month",
    "hourly": "hour",
    "nightly": "night",
}
_SMALL_NUMBERS = {
    word: Decimal(value)
    for value, word in enumerate(
        ("two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"), start=2
    )
}
_WHOLE_WORD = r"(?<![^\W_])(?:{})(?![^\W_])"
_SEP = r"[\s\-]+"
_COUNT = rf"(?P<count>\d+(?:\.\d+)?|{'|'.join(_SMALL_NUMBERS)})"
# One period list for every connector, with or without a count in front: "every night", "each
# shift", "every other night", "twice a night", "2 times per shift", "once a night".
_PERIODS = "day|week|month|hour|night|shift"


def _connected(connectors: str) -> str:
    return rf"(?:{connectors}){_SEP}(?P<period>{_PERIODS})"


_EVERYDAY = r"(?P<everyday>everyday)"
_EVERY_OTHER = rf"every{_SEP}other{_SEP}(?P<other>{_PERIODS})"
# Read alone, "every" and "each" take a period; after a count "a", "an" and "per" do too.
_EVERY = f"{_EVERYDAY}|{_connected('every|each')}|{_EVERY_OTHER}"
_COUNTED_EACH = (
    rf"(?:{_SEP}(?:(?P<adverb>{'|'.join(_ADVERBS)})|{_connected('an|a|per|every|each')}"
    rf"|{_EVERYDAY}|{_EVERY_OTHER})"
    # After a count, "/" (spaces around it are fine) and a period too: "2x/day", "twice / week".
    rf"|[ \t]*/[ \t]*(?P<slashed>{_PERIODS}))"
)
# One pattern for each family of spellings; each match is a frequency, read with `_meaning`.
_FREQUENCY_PATTERNS = tuple(
    re.compile(_WHOLE_WORD.format(body), re.IGNORECASE)
    for body in (
        rf"(?P<abbreviation>{'|'.join(_ABBREVIATIONS)})",
        rf"(?P<adverb>{'|'.join(_ADVERBS)})",
        _EVERY,
        rf"once{_SEP}(?:(?P<adverb>{'|'.join(_ADVERBS)})|{_connected('an|a|per')})",
        rf"(?P<times>twice|thrice){_COUNTED_EACH}",
        rf"{_COUNT}(?:{_SEP}times|{_SEP}x|(?<=\d)x){_COUNTED_EACH}",
    )
)
# The periods "a" or "an" takes with no count, right after a dose, volume or drop unit: not hour
# or minute, as "1000 units an hour" is a rate in practice.
_DOSE_PERIODS = "day|week|month|night|shift"
# "a" or "an" and one of those periods, whole words ("a day", "an-night"), read as a frequency
# only right after such a unit ("15 mg a day").
_A_PERIOD = re.compile(_WHOLE_WORD.format(rf"an?{_SEP}(?P<period>{_DOSE_PERIODS})"), re.IGNORECASE)
# A time word after that period, past spaces or a line break, makes it say when, not how often:
# "15 mg a day ago", "1 L a night before".
_WHEN_AFTER = re.compile(
    r"(?>\s+)(?:ago|before|prior|earlier|early|later|late)(?![^\W_])", re.IGNORECASE
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
    (re.compile(r"millilit(?:er|re)s?", re.IGNORECASE), Ucum.ML),
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
    **dict.fromkeys(("milligram", "milligrams"), "mg"),
    **dict.fromkeys(("microgram", "micrograms"), "mcg"),
    **dict.fromkeys(("gram", "grams"), "g"),
    "l": "l",
    **dict.fromkeys(("liter", "liters", "litre", "litres"), "l"),
    "ml": "ml",
    "cc": "ml",
    **dict.fromkeys(("milliliter", "milliliters", "millilitre", "millilitres"), "ml"),
    "gtt": "gtt",
    "gtts": "gtt",
    **dict.fromkeys(("oz", "ozs", "ounce", "ounces"), "oz"),
}
# The unit spellings the code knows, folded. A letter run right after whole digits that is one of
# them ("HR121bpm") leaves the digits a number, and a note number followed by one has a unit.
_UNIT_SPELLINGS = frozenset(
    {alias.casefold() for alias, _ in _ALIASES}
    | set(_COMPARED_UNITS)
    | {"bpm", "cpm", "mmhg", "lpm", "gtts", "kcal", "cm", "mm"}
    | {"degf", "degc", "fahrenheit", "celsius", "kilogram", "kilograms", "pound", "pounds"}
)
# The only words that count as a denominator after "/" or "per", compared by meaning. Any other
# word ends the unit with no rate.
_DENOMINATORS = {
    **dict.fromkeys(("h", "hr", "hrs", "hour", "hours"), "hour"),
    **dict.fromkeys(("m", "min", "mins", "minute", "minutes"), "minute"),
    **dict.fromkeys(("d", "day", "days"), "day"),
    **dict.fromkeys(("wk", "wks", "week", "weeks"), "week"),
    **dict.fromkeys(("mo", "mos", "month", "months"), "month"),
    **dict.fromkeys(("shift", "shifts"), "shift"),
    **dict.fromkeys(("kg", "kgs", "kilogram", "kilograms"), "kg"),
    **dict.fromkeys(("ml", "cc", "milliliter", "milliliters", "millilitre", "millilitres"), "ml"),
    **dict.fromkeys(("l", "liter", "liters", "litre", "litres"), "l"),
    **dict.fromkeys(("dl", "deciliter", "deciliters", "decilitre", "decilitres"), "dl"),
}
# The time words a number can be followed by ("2 hours", "x 8 hrs", "20 mins"), by meaning. The
# one-letter "m" and "d" are left out: after a number they are as often metres or a word.
_TIME_WORDS = {
    spelling: meaning
    for spelling, meaning in _DENOMINATORS.items()
    if meaning in {"hour", "minute", "day", "week"} and spelling not in {"m", "d"}
}
_LITRES_PER_MINUTE = "lpm"
_TEMPERATURE_LETTERS = frozenset("cf")  # "c/o" and "f/u" are shorthand, whatever the letter after
_RATE_LETTERS = frozenset("hdm")  # after u, l or g: "u/h", "g/d" and "L/m" are rates, "u/a" is not
_PER_LITRE_UNITS = frozenset("ug")  # "g/L" and "u/L" are per litre, not shorthand
# Whitespace inside a rate includes a line break, so "5 mg/" then "hr" on the next line is a rate.
_PER = re.compile(r"\s+per\s+", re.IGNORECASE)
_SLASH = re.compile(r"\s*/\s*")
# "units / HR 88" may be a heart rate instead of per hour: a "/", the spelling "hr", then (spaces,
# ":", "=", a dash or "of") and a heart-rate-like number: two or three digits on the same line,
# not a time like "0800" or "10am", a volume or a weight. "bpm", "/min", "/mins" or "/minute" may
# follow it. A dose, volume or weight unit of two letters or more after the number
# ("units/hr = 10 mL/hr") means it is not a heart rate. A single letter or "drop" there is a word
# as often as a unit ("HR 88 L radial", "HR 88 u/a", "HR 88 drops to 60") and "CC:" is a chief
# complaint, so neither says anything. The unit must end there: "HR 88 CCU" and "HR 88 mgmt" are
# words.
_NOT_A_HEART_RATE_UNIT = (
    r"(?![ \t]*(?:units?|iu|mg|mcg|ug|gm|kg|ml|cc(?![ \t]*:)|meq|mmol|gtts?)(?!\w))"
)
_HEART_RATE_NUMBER = re.compile(
    r"(?:[ \t]*[:=\-\u2013\u2014][ \t]*|[ \t]+of[ \t]+|[ \t]+)"
    rf"\d{{2,3}}{_NOT_A_HEART_RATE_UNIT}"
    r"(?:(?![\w:/]|\.\d)|[ \t]*bpm(?!\w)|/[ \t]*min(?:s|utes?)?(?!\w))",
    re.IGNORECASE,
)
# A denominator no line can write: it equals only itself, so a line that repeats the same
# "/ HR 88" form passes, and any other reading of that number with a unit flags.
_AMBIGUOUS = "?"
type NumberValue = tuple[str | Decimal, ...]
# How often, by meaning: (a count, what it is per) such as (2, "day"), or ("abbreviation", "bid").
type FrequencyMeaning = tuple[str | Decimal, str]
_WINDOW = 64  # typed characters read after a number (a unit, a bare rate) or a unit (a rate)


@dataclass(frozen=True, slots=True)
class WrittenFrequency:
    """A frequency as typed, with its span in the text and what it means."""

    text: str
    span: Span
    meaning: FrequencyMeaning  # "daily" and "every day" mean the same; "BID" only itself


@dataclass(frozen=True, slots=True)
class WrittenUnit:
    """The unit written right after a number."""

    unit: Ucum | None  # the unit the alias table reads, if it reads one
    compared: str | None  # the dose or volume unit compared by spelling, if one is written
    rate: tuple[str, ...]  # what it is per ("hour"; "kg", "minute"), empty when it is no rate
    end: int  # where the unit, with its rate, ends in the text


def numbers_in(text: str) -> list[tuple[str, Span]]:
    """Every number, "/" group or mixed number as written, with its span in `text`.

    Digits that are part of a word ("D5LR", "q4h") are skipped.
    """
    return _scan(text)[0]


def words_with_numbers(text: str) -> list[tuple[str, Span]]:
    """Words that carry a number that isn't read as one, with their spans in `text`.

    These are words with digits inside ("q4h", "D5W", "HR121bpmRR20"), the number words one to
    ten, "half" and "twice". They can't be compared by value, only as whole words. Frequencies
    are read by meaning instead (see `frequencies_in`).
    """
    in_words = _scan(text)[1]
    out: list[tuple[str, Span]] = []
    for word in _WORD.finditer(text):
        start, end = word.span()
        folded = word.group().casefold()
        if folded in _NUMBER_WORDS or any(start <= i < end for i in in_words):
            out.append((word.group(), Span(start=start, end=end)))
    return out


def frequencies_in(text: str) -> list[WrittenFrequency]:
    """Every frequency in `text` as typed, left to right, each with its meaning.

    Where two readings start at the same place the longer wins, and a reading that starts inside
    an earlier one is dropped, so "once daily" is one frequency.
    """
    readings = [
        WrittenFrequency(match.group(), Span(start=match.start(), end=match.end()), _meaning(match))
        for pattern in _FREQUENCY_PATTERNS
        for match in pattern.finditer(text)
    ]
    readings.extend(_after_a_unit(text))
    readings.sort(key=lambda reading: (reading.span.start, -reading.span.end))
    out: list[WrittenFrequency] = []
    for reading in readings:
        if out and reading.span.start < out[-1].span.end:
            continue
        out.append(reading)
    return out


def _after_a_unit(text: str) -> list[WrittenFrequency]:
    """Each "a" or "an" and a period right after a dose, volume or drop unit written with no rate
    ("15 mg a day"), as typed from the "a": one per that period. A period a time word follows
    ("15 mg a day ago") is no frequency.

    A unit has no digit in it, so only the number right before each "a" or "an" is read with its
    unit, which must end where the spaces, line breaks or hyphens before the "a" start.
    """
    found = list(_A_PERIOD.finditer(text))
    if not found:
        return []
    numbers = numbers_in(text)
    out: list[WrittenFrequency] = []
    for match in found:
        if _WHEN_AFTER.match(text, match.end()):
            continue
        gap = match.start()
        while gap > 0 and (text[gap - 1].isspace() or text[gap - 1] == "-"):
            gap -= 1
        before = bisect_right(numbers, gap, key=lambda number: number[1].end) - 1
        if gap == match.start() or before < 0:
            continue
        unit = written_unit(text, numbers[before][1])
        if unit is None or unit.compared is None or unit.rate or unit.end != gap:
            continue
        span = Span(start=match.start(), end=match.end())
        meaning = (Decimal(1), match["period"].casefold())
        out.append(WrittenFrequency(match.group(), span, meaning))
    return out


def _meaning(match: re.Match[str]) -> FrequencyMeaning:
    groups = match.groupdict()
    if groups.get("abbreviation"):
        return ("abbreviation", match["abbreviation"].casefold())
    count = Decimal(1)
    if groups.get("times"):
        count = Decimal(2 if match["times"].casefold() == "twice" else 3)
    elif groups.get("count"):
        written = match["count"].casefold()
        count = _SMALL_NUMBERS.get(written) or Decimal(written)
    if groups.get("other"):
        return (count, f"other {match['other'].casefold()}")
    if groups.get("adverb"):
        return (count, _ADVERBS[match["adverb"].casefold()])
    if groups.get("everyday"):
        return (count, "day")
    if groups.get("period"):
        return (count, match["period"].casefold())
    if groups.get("slashed"):
        return (count, match["slashed"].casefold())
    raise ValueError(f"a frequency pattern matched without a reading: {match.group()!r}")


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
    compared = None if spelling is None else _COMPARED_UNITS.get(spelling)
    end = max(unit_end, spelling_end)
    if spelling == _LITRES_PER_MINUTE:
        compared, rate = "l", ("minute",)
    else:
        rate, end = ((), end) if compared is None else _rate_after(text, end)
    return WrittenUnit(
        unit=unit,
        compared=compared,
        rate=rate,
        end=end,
    )


def bare_rate_end_after(text: str, number_span: Span) -> tuple[tuple[str, ...], int]:
    """The rate written right after a number with no unit between ("100/hr", "100 per hour").

    Returns it with where it ends in `text` (the number's end when there is none).
    """
    return _rate_after(text, number_span.end)


def time_after(text: str, number_span: Span) -> tuple[str, int] | None:
    """The time word written right after a number ("2 hours", "8hrs"), by meaning ("hour"), and
    where it ends in `text`; None when there is none. It must be a whole word."""
    folded, origin = _fold_after(text, number_span.end)
    letters = _LETTERS.match(folded, len(folded) - len(folded.lstrip(" \t")))
    if letters is None or folded[letters.end() : letters.end() + 1].isalnum():
        return None
    meaning = _TIME_WORDS.get(letters.group().casefold())
    return None if meaning is None else (meaning, origin[letters.end() - 1] + 1)


def _rate_after(text: str, unit_end: int) -> tuple[tuple[str, ...], int]:
    """What the unit ending at `unit_end` is per ("/hr", " per kg / min"), and where the rate ends.

    Each denominator is a whole word from the closed set above; any other word ends the rate.
    """
    folded, origin = _fold_after(text, unit_end)
    rate: list[str] = []
    position = 0
    end = unit_end
    while True:
        slash = _SLASH.match(folded, position)
        per = None if slash else _PER.match(folded, position)
        separator = slash or per
        letters = None if separator is None else _LETTERS.match(folded, separator.end())
        if letters is None or folded[letters.end() : letters.end() + 1].isdigit():
            break
        spelling = letters.group().casefold()
        denominator = _DENOMINATORS.get(spelling)
        if denominator is None:
            break
        if slash and spelling == "hr" and _HEART_RATE_NUMBER.match(folded, letters.end()):
            # "units / HR 88": per hour, or a "/" before a heart rate? Unsure, so it equals nothing.
            rate.append(_AMBIGUOUS)
            end = origin[letters.end() - 1] + 1
            break
        rate.append(denominator)
        position = end_in_folded = letters.end()
        end = origin[end_in_folded - 1] + 1
    return tuple(rate), end


def _spelling_after(text: str, number_span: Span) -> tuple[str, int] | None:
    """A known unit spelling written right after a number, folded, and where it ends in `text`."""
    folded, origin = _fold_after(text, number_span.end)
    letters = _LETTERS.match(folded, len(folded) - len(folded.lstrip(" \t")))
    if letters is None or not _word_ends(folded, letters.end()):
        return None
    spelling = letters.group().casefold()
    stop = letters.end()
    if spelling in ("fl", "fluid"):  # "fl oz" and "fluid ounces" are the ounce, "fl" is nothing
        fluid = _FLUID_OUNCE.match(folded, stop)
        if fluid is None or not _word_ends(folded, fluid.end()):
            return None
        spelling, stop = "oz", fluid.end()
    if spelling not in _UNIT_SPELLINGS:
        return None
    return spelling, origin[stop - 1] + 1


def _fold_after(text: str, start: int) -> tuple[str, list[int]]:
    """The typed characters after a number, folded, and the typed index behind each one."""
    folded: list[str] = []
    origin: list[int] = []
    stop = min(len(text), start + _WINDOW)
    while stop < len(text) and text[stop].isalnum():
        stop += 1  # finish the word the end of the read cut in half
    for index in range(start, stop):
        char = _DEGREE_LOOKALIKES.get(text[index], text[index])
        for part in unicodedata.normalize("NFKC", char):
            folded.append(part)
            origin.append(index)
    return "".join(folded), origin


def _read_unit(folded: str) -> tuple[Ucum, int] | None:
    """The unit at the start of the folded characters after a number, and where it ends."""
    if folded.startswith("#"):
        return (Ucum.LB, 1) if _word_ends(folded, 1) and folded[1:2] != "/" else None
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
    """A unit isn't followed by a letter or a digit ("2 Foley"), or by one-letter shorthand.

    A "/" after the unit is allowed: the unit may start a rate ("100 mL/hr"). Whether it does is
    decided later, since only dose, volume and drop units take one ("37.8C/HR 110" has none). The
    "/" is not allowed when the unit is one letter and the "/" is followed by one letter more, as
    in "c/o", "f/u" and "u/a".
    """
    following = folded[stop : stop + 1]
    if following.isalnum():
        return False
    return following != "/" or not _is_shorthand(folded, stop)


def _is_shorthand(folded: str, stop: int) -> bool:
    """One-letter unit, "/", one more letter, then no digit: "c/o", "f/u", "u/a".

    A digit after the second letter means it isn't shorthand ("c/o2"). After u, l or g the letters
    h, d and m make a rate instead ("u/h", "g/d", "L/m").
    """
    if not _ends_a_one_letter_word(folded, stop):
        return False
    second = _LETTERS.match(folded, stop + 1)
    if second is None or len(second.group()) != 1 or folded[second.end() :][:1].isdigit():
        return False
    first, letter = folded[stop - 1].casefold(), second.group().casefold()
    if first in _PER_LITRE_UNITS and letter == "l":
        return False
    return first in _TEMPERATURE_LETTERS or letter not in _RATE_LETTERS


def _ends_a_one_letter_word(folded: str, stop: int) -> bool:
    """Whether the characters just before `stop` are one letter, not the end of a longer word."""
    last_is_letter = folded[stop - 1].isalpha()
    letter_before_it = stop >= 2 and folded[stop - 2].isalpha()
    return last_is_letter and not letter_before_it
