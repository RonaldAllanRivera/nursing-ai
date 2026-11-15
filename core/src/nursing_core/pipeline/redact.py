"""Replace known identifiers with tokens before a note goes to the AI, and put them back after.

This is data minimisation: the names and identifiers the record holds, plus common identifier
patterns, never reach the model. The same rules run for every facility.

Identity strings are matched on a folded copy of the note (accents dropped, case ignored, one
code point at a time) and every match is mapped back to the exact characters the nurse typed.
Patterns run on the typed text. All hits then merge where they overlap, so a token always
covers whole characters and the mapping always holds the exact typed spelling.
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import date

from nursing_core.domain.patient import PatientIdentity

_MONTHS = [
    ("January", "Jan"),
    ("February", "Feb"),
    ("March", "Mar"),
    ("April", "Apr"),
    ("May", "May"),
    ("June", "Jun"),
    ("July", "Jul"),
    ("August", "Aug"),
    ("September", "Sep"),
    ("October", "Oct"),
    ("November", "Nov"),
    ("December", "Dec"),
]
_STATES = re.findall(
    r"[A-Z]{2}",
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ"
    " NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY",
)
# Codes that are also everyday clinical abbreviations: a number after them is not a ZIP.
_CLINICAL_CODES = set(re.findall(r"[A-Z]{2}", "CO CT ID IN LA MD ME MS NC OK OR PA SC"))
_TOKEN_SHAPE = re.compile(r"\[[A-Z_]+_\d+\]")
# Highest precedence first: ties between hits of equal width go to the earlier kind.
_KINDS = [
    "PATIENT",
    "NICKNAME",
    "RELATIVE",
    "RECORD_NO",
    "ADDRESS",
    "POSTAL_CODE",
    "BIRTH_DATE",
    "EMAIL",
    "URL",
    "IP",
    "SSN",
    "PHONE",
    "DATE",
    "ZIP",
]
# "Not touching a letter" (digits and underscores do not protect a name).
_NOT_AFTER_LETTER = r"(?<![^\W\d_])"
_NOT_BEFORE_LETTER = r"(?![^\W\d_])"


@dataclass(frozen=True, slots=True)
class Redacted:
    text: str  # the note with tokens in place of identifiers
    mapping: dict[str, str]  # token -> the exact original spelling it replaced


@dataclass(frozen=True, slots=True)
class _Hit:
    start: int
    end: int
    kind: str


@dataclass(frozen=True, slots=True)
class _Folded:
    text: str  # case-folded, accents dropped
    origin: list[int]  # origin[i] = index in `raw` of the code point that produced text[i]
    raw: str


_APOSTROPHES = str.maketrans({0x2018: "'", 0x2019: "'"})


def _fold(raw: str) -> _Folded:
    chars: list[str] = []
    origin: list[int] = []
    for index, code_point in enumerate(raw):
        for part in unicodedata.normalize("NFKD", code_point):
            for char in unicodedata.normalize("NFKD", part.casefold()):
                if not unicodedata.category(char).startswith("M"):
                    chars.append(char.translate(_APOSTROPHES))
                    origin.append(index)
    return _Folded("".join(chars), origin, raw)


def _raw_span(folded: _Folded, start: int, end: int) -> tuple[int, int]:
    """The typed characters behind folded[start:end], with any accent marks that follow."""
    raw_end = folded.origin[end - 1] + 1
    while raw_end < len(folded.raw) and unicodedata.category(folded.raw[raw_end]).startswith("M"):
        raw_end += 1
    return folded.origin[start], raw_end


def _words(term: str) -> list[str]:
    """Words of a name, whole and split on hyphens and apostrophes; at least 2 letters each."""
    parts = [*term.split(), *re.split(r"[\s'\u2010\u2011\u2019-]+", term)]
    return [w for w in parts if sum(c.isalpha() for c in w) >= 2]


def _birth_date_forms(d: date) -> list[str]:
    forms = [d.isoformat()]
    for sep in "/-":
        for a, b in ((d.month, d.day), (d.day, d.month)):
            forms.append(f"{a:02d}{sep}{b:02d}{sep}{d.year}")
            forms.append(f"{a}{sep}{b}{sep}{d.year}")
    full, abbr = _MONTHS[d.month - 1]
    for name in (full, abbr):
        forms.append(f"{name} {d.day}, {d.year}")
        forms.append(f"{d.day} {name} {d.year}")
    return forms


def _identity_strings(identity: PatientIdentity) -> list[tuple[str, str]]:
    """(kind, typed string) pairs from the record."""
    given, middle, family = identity.given_name, identity.middle_name, identity.family_name
    names = [f"{given} {family}"]
    if middle:
        names.append(f"{given} {middle} {family}")
    if identity.suffix:
        names += [f"{n} {identity.suffix}" for n in names]
    for part in (given, middle or "", family):
        names += _words(part)
    if len(given.split()) > 1:
        names.append(given)
    pairs = [("PATIENT", n) for n in names]
    for nick in identity.nicknames:
        pairs += [("NICKNAME", t) for t in (nick, *_words(nick))]
    for rel in identity.relatives:
        pairs += [("RELATIVE", t) for t in (rel.name, *_words(rel.name))]
    pairs.append(("RECORD_NO", identity.record_number))
    pairs += [("ADDRESS", identity.address)] if identity.address else []
    pairs += [("BIRTH_DATE", f) for f in _birth_date_forms(identity.birth_date)]
    return [(kind, term) for kind, term in pairs if term.strip()]


def _digit_postal_code(identity: PatientIdentity) -> str | None:
    """The folded postal code when it is made only of digits (it then needs address context)."""
    folded = _fold((identity.postal_code or "").strip()).text
    return folded if re.fullmatch(r"[0-9]+", folded) else None


def _identity_terms(identity: PatientIdentity) -> list[tuple[str, str]]:
    """Folded (term, kind) pairs, longest first; the best kind wins for a repeated term."""
    pairs = _identity_strings(identity)
    if identity.postal_code and _digit_postal_code(identity) is None:
        pairs.append(("POSTAL_CODE", identity.postal_code))
    best: dict[str, str] = {}
    for kind, term in sorted(pairs, key=lambda p: _KINDS.index(p[0])):
        best.setdefault(" ".join(_fold(term).text.split()), kind)
    return sorted(best.items(), key=lambda item: len(item[0]), reverse=True)


def _identity_regex(terms: list[tuple[str, str]]) -> re.Pattern[str]:
    """One regex, one capture group per term, so the group number says which term matched."""
    return re.compile("|".join(f"({_term_regex(term)})" for term, _ in terms))


def _term_regex(term: str) -> str:
    """A term's words joined by any whitespace; its edges must not touch a letter.

    An edge that is not a letter (a digit, a bracket) gets no rule, so removing a neighbour
    can never create a match that was not there before.
    """
    body = r"\s+".join(re.escape(w) for w in term.split())
    before = _NOT_AFTER_LETTER if term[0].isalpha() else ""
    after = _NOT_BEFORE_LETTER if term[-1].isalpha() else ""
    return before + body + after


_ADDRESS_WORD = re.compile(r"[^\W\d_]{3,}")
_ZIP_WORDS = ["zipcode", "zip", "postcode", "postal"]
_GAP = r"(?:[ \t,:]|code)*\Z"
_STATE_BEFORE = re.compile(_NOT_AFTER_LETTER + r"([^\W\d_]{2})" + _GAP)


def _has_address_context(folded: _Folded, start: int, words: re.Pattern[str]) -> bool:
    """True when an address word, state code or "zip"/"postal" comes right before, same line."""
    line_start = max(folded.text.rfind("\n", 0, start), folded.text.rfind("\r", 0, start)) + 1
    before = folded.text[line_start:start]
    if words.search(before):
        return True
    state = _STATE_BEFORE.search(before)
    if state is None:
        return False
    first = line_start + state.start(1)
    typed = folded.raw[folded.origin[first] : folded.origin[first + 1] + 1]
    return typed in _STATES


def _postal_hits(folded: _Folded, identity: PatientIdentity) -> list[_Hit]:
    """A record postal code made only of digits counts only after address context."""
    digits = _digit_postal_code(identity)
    if digits is None:
        return []
    address_words = set(_ADDRESS_WORD.findall(_fold(identity.address or "").text))
    words = "|".join(sorted([*_ZIP_WORDS, *address_words], key=len, reverse=True))
    context = re.compile(_NOT_AFTER_LETTER + "(?:" + words + ")" + _GAP)
    hits: list[_Hit] = []
    for m in re.finditer(re.escape(digits), folded.text):
        if _has_address_context(folded, m.start(), context):
            hits.append(_Hit(*_raw_span(folded, m.start(), m.end()), "POSTAL_CODE"))
    return hits


def _identity_hits(text: str, identity: PatientIdentity) -> list[_Hit]:
    folded = _fold(text)
    terms = _identity_terms(identity)
    hits = _postal_hits(folded, identity)
    for m in _identity_regex(terms).finditer(folded.text):
        kind = terms[(m.lastindex or 1) - 1][1]
        hits.append(_Hit(*_raw_span(folded, m.start(), m.end()), kind))
    return hits


def mentions_identity(text: str, identity: PatientIdentity) -> bool:
    """True when the text holds any identity string the record knows."""
    return bool(_identity_hits(text, identity))


def _month_names(names: list[str]) -> str:
    return "|".join(n for name in names for n in (name, name.upper()))


_FULL_MONTHS = _month_names([full for full, _ in _MONTHS if full != "May"])
_TITLE_ABBREVIATIONS = "|".join(abbr for full, abbr in _MONTHS if full != "May") + "|Sept"
_UPPER_ABBREVIATIONS = _TITLE_ABBREVIATIONS.upper()
# Month names count only in Title or UPPER case. Upper-case abbreviations and "May" are also
# everyday words ("DEC 30" for decreased, "may need"), so they count only when a year follows.
_ANY_YEAR_MONTH = f"{_FULL_MONTHS}|{_TITLE_ABBREVIATIONS}"
_WITH_YEAR_MONTH = f"{_UPPER_ABBREVIATIONS}|May|MAY"
_DAY = r"(?<![\w/])(?:3[01]|[12]\d|0?[1-9])(?:st|nd|rd|th)?(?![\w/])"
_YEAR = r",?\s+(?:19|20)\d{2}(?!\d)"
_OCTET = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
_PHONE = "|".join(
    [
        r"\+\d{1,3}[ .-]?\(?\d{2,4}\)?[ .-]?\d{3,4}[ .-]?\d{3,4}",
        r"\(\d{2,4}\)\s?\d{3,4}[ .-]\d{4}",
        r"\d{3}[ .-]\d{3}[ .-]\d{4}",
        r"0\d{3}[ .-]\d{3}[ .-]\d{4}",
        r"09\d{9}",
        r"0\d-\d{4}-\d{4}",
    ]
)
_DATE = "|".join(
    [
        r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)",
        r"(?<![\d/-])\d{1,2}([/-])\d{1,2}\1(?:\d{4}|\d{2})(?![\d/-])",
        rf"{_DAY}\s+(?:{_ANY_YEAR_MONTH})(?!\w)(?:{_YEAR})?",
        rf"{_DAY}\s+(?:{_WITH_YEAR_MONTH})(?!\w){_YEAR}",
        rf"(?<!\w)(?:{_ANY_YEAR_MONTH})\s+{_DAY}(?:{_YEAR})?",
        rf"(?<!\w)(?:{_WITH_YEAR_MONTH})\s+{_DAY}{_YEAR}",
    ]
)
_ZIP_STATES = "|".join(s for s in _STATES if s not in _CLINICAL_CODES)
# (kind, pattern, group holding the match).
_PATTERNS: list[tuple[str, re.Pattern[str], int]] = [
    (
        "EMAIL",
        re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"),
        0,
    ),
    ("URL", re.compile(r"(?<!\w)(?:https?://|www\.)\S*[^\s.,;:)]", re.IGNORECASE), 0),
    ("IP", re.compile(rf"(?<![\d.])(?:{_OCTET}\.){{3}}{_OCTET}(?!\d)(?!\.\d)"), 0),
    ("SSN", re.compile(r"(?<![\d-])\d{3}-\d{2}-\d{4}(?!\d)(?!-\d)"), 0),
    ("PHONE", re.compile(rf"(?<![\w+])(?:{_PHONE})(?!\d)"), 0),
    ("DATE", re.compile(_DATE), 0),
    ("ZIP", re.compile(rf"(?<![A-Za-z])(?:{_ZIP_STATES}),?\s+(\d{{5}}(?:-\d{{4}})?)(?!\d)"), 1),
]
_AGE_UNIT = r"(?:y/o|y\.o\.?|yo|years?|yrs?)(?!\w)"
_AGE = re.compile(
    rf"(?<![\d.])(\d{{2,3}})(?=\s*-?\s*{_AGE_UNIT})|(?<!\w)aged?\s+(\d{{2,3}})(?!\d)",
    re.IGNORECASE,
)


def _pattern_hits(text: str) -> list[_Hit]:
    return [
        _Hit(m.start(group), m.end(group), kind)
        for kind, pattern, group in _PATTERNS
        for m in pattern.finditer(text)
    ]


def _cover(group: list[_Hit]) -> _Hit:
    widest = min(group, key=lambda h: (h.start - h.end, _KINDS.index(h.kind)))
    return _Hit(min(h.start for h in group), max(h.end for h in group), widest.kind)


def _merge(hits: list[_Hit]) -> list[_Hit]:
    """Overlapping hits become one span with the widest member's kind (ties: earlier kind)."""
    merged: list[_Hit] = []
    group: list[_Hit] = []
    group_end = 0
    for hit in sorted(hits, key=lambda h: (h.start, h.end)):
        if group and hit.start >= group_end:
            merged.append(_cover(group))
            group = []
        group.append(hit)
        group_end = max(group_end, hit.end)
    return [*merged, _cover(group)] if group else merged


def _age_spans(text: str, taken: list[_Hit]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for m in _AGE.finditer(text):
        group = 1 if m.group(1) else 2
        start, end = m.start(group), m.end(group)
        if int(m.group(group)) >= 90 and not any(start < t.end and t.start < end for t in taken):
            spans.append((start, end))
    return spans


def redact(text: str, identity: PatientIdentity) -> Redacted:
    """Replace identifiers with `[KIND_n]` tokens; each distinct spelling gets its own token."""
    hits = _merge([*_identity_hits(text, identity), *_pattern_hits(text)])
    mapping: dict[str, str] = {}
    by_spelling: dict[tuple[str, str], str] = {}
    counters: dict[str, int] = {}
    # Ages are replaced one way: the literal "90+", no token and no mapping entry.
    replacements = [(start, end, "90+") for start, end in _age_spans(text, hits)]
    for hit in hits:
        spelling = text[hit.start : hit.end]
        token = by_spelling.get((hit.kind, spelling))
        if token is None:
            n = counters.get(hit.kind, 0) + 1
            while f"[{hit.kind}_{n}]" in text:
                n += 1
            counters[hit.kind] = n
            token = f"[{hit.kind}_{n}]"
            by_spelling[(hit.kind, spelling)] = token
            mapping[token] = spelling
        replacements.append((hit.start, hit.end, token))
    out: list[str] = []
    pos = 0
    for start, end, replacement in sorted(replacements):
        out += [text[pos:start], replacement]
        pos = end
    out.append(text[pos:])
    return Redacted("".join(out), mapping)


def restore(text: str, mapping: dict[str, str]) -> str:
    """Put the exact original text back for every known token, in one pass."""
    return _TOKEN_SHAPE.sub(lambda m: mapping.get(m.group(), m.group()), text)
