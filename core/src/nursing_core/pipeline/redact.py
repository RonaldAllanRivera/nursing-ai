"""Replace known identifiers with tokens before a note goes to the AI, and put them back after.

This is data minimisation: the names and identifiers the record holds, plus common identifier
patterns, never reach the model. The same rules run for every facility.
"""

import re
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
_STATES = (
    "AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ"
    "|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY"
)
_TOKEN_SHAPE = re.compile(r"\[[A-Z_]+_\d+\]")
# Highest precedence first: when one string is claimed by several kinds, the first kind wins.
_IDENTITY_KINDS = ["PATIENT", "NICKNAME", "RELATIVE", "RECORD_NO", "ADDRESS", "POSTAL_CODE"]


@dataclass(frozen=True, slots=True)
class Redacted:
    text: str  # the note with tokens in place of identifiers
    mapping: dict[str, str]  # token -> the exact original spelling it replaced


@dataclass(frozen=True, slots=True)
class _Hit:
    start: int
    end: int
    kind: str | None  # None: replaced by `fixed`, never restored
    fixed: str = ""


def _key(term: str) -> str:
    return " ".join(term.split()).lower()


def _words(term: str) -> list[str]:
    return [w for w in term.split() if sum(c.isalpha() for c in w) >= 2]


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


def _identity_terms(identity: PatientIdentity) -> dict[str, str]:
    """Known strings (lower-cased, whitespace collapsed) -> kind, best kind winning."""
    found: dict[str, list[str]] = {kind: [] for kind in _IDENTITY_KINDS}
    given, middle, family = identity.given_name, identity.middle_name, identity.family_name
    names = [f"{given} {family}"]
    if middle:
        names.append(f"{given} {middle} {family}")
    if identity.suffix:
        names += [f"{n} {identity.suffix}" for n in names]
    found["PATIENT"] += names
    for part in (given, middle or "", family):
        found["PATIENT"] += _words(part)
    if len(given.split()) > 1:
        found["PATIENT"].append(given)
    for nick in identity.nicknames:
        found["NICKNAME"] += [nick, *_words(nick)]
    for rel in identity.relatives:
        found["RELATIVE"] += [rel.name, *_words(rel.name)]
    found["RECORD_NO"].append(identity.record_number)
    found["ADDRESS"] += [identity.address] if identity.address else []
    found["POSTAL_CODE"] += [identity.postal_code] if identity.postal_code else []
    terms: dict[str, str] = {}
    for kind in _IDENTITY_KINDS:
        for term in found[kind]:
            if term.strip():
                terms.setdefault(_key(term), kind)
    for form in _birth_date_forms(identity.birth_date):
        terms.setdefault(_key(form), "BIRTH_DATE")
    return terms


def _identity_regex(terms: dict[str, str]) -> re.Pattern[str]:
    parts = [
        r"\s+".join(re.escape(w) for w in t.split()) for t in sorted(terms, key=len, reverse=True)
    ]
    return re.compile(r"(?<!\w)(?:" + "|".join(parts) + r")(?!\w)", re.IGNORECASE)


def mentions_identity(text: str, identity: PatientIdentity) -> bool:
    """True when the text holds any identity string the record knows."""
    return _identity_regex(_identity_terms(identity)).search(text) is not None


_D = r"(?<!\d)"
_MONTH_NAMES = "|".join([full for full, _ in _MONTHS] + [abbr for _, abbr in _MONTHS] + ["Sept"])
_DAY = r"(?:3[01]|[12]\d|0?[1-9])(?:st|nd|rd|th)?"
_YEAR = r"(?:19|20)\d{2}"
_OCTET = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
_PHONE = "|".join(
    [
        r"\+\d{1,3}[ .-]?\(?\d{2,4}\)?[ .-]?\d{3,4}[ .-]?\d{3,4}",
        r"\(\d{2,4}\)\s?\d{3,4}[ .-]\d{4}",
        r"\d{3}[.-]\d{3}[.-]\d{4}",
        r"0\d{3}[ .-]\d{3}[ .-]\d{4}",
        r"09\d{9}",
        r"0\d-\d{4}-\d{4}",
    ]
)
# (kind, pattern, group holding the match). Applied in this order.
_PATTERNS: list[tuple[str, re.Pattern[str], int]] = [
    (
        "EMAIL",
        re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"),
        0,
    ),
    ("URL", re.compile(r"(?<!\w)(?:https?://|www\.)\S*[^\s.,;:)]"), 0),
    ("IP", re.compile(rf"(?<![\d.])(?:{_OCTET}\.){{3}}{_OCTET}(?!\d)(?!\.\d)"), 0),
    ("SSN", re.compile(r"(?<![\d-])\d{3}-\d{2}-\d{4}(?!\d)(?!-\d)"), 0),
    ("PHONE", re.compile(rf"(?<![\w+])(?:{_PHONE})(?!\d)"), 0),
    (
        "DATE",
        re.compile(
            "|".join(
                [
                    r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)",
                    r"(?<![\d/-])\d{1,2}([/-])\d{1,2}\1(?:\d{4}|\d{2})(?![\d/-])",
                    rf"(?<!\w){_DAY}\s+(?:{_MONTH_NAMES})(?!\w)(?:,?\s+{_YEAR}(?!\d))?",
                    rf"(?<!\w)(?:{_MONTH_NAMES})\s+{_DAY}(?![\w])(?:,?\s+{_YEAR}(?!\d))?",
                ]
            ),
            re.IGNORECASE,
        ),
        0,
    ),
    (
        "ZIP",
        re.compile(rf"(?<![A-Za-z])(?:{_STATES}),?\s+(\d{{5}}(?:-\d{{4}})?)(?!\d)"),
        1,
    ),
]
_AGE = re.compile(
    r"(?<![\d.])(\d{2,3})(?=\s*-?\s*(?:y/o(?!\w)|y\.o\.|yo(?!\w)|(?:years?|yrs?)[\s-]*old(?!\w)))"
    r"|(?<!\w)aged\s+(\d{2,3})(?!\d)",
    re.IGNORECASE,
)


def _overlaps(hit: _Hit, claimed: list[_Hit]) -> bool:
    return any(hit.start < c.end and c.start < hit.end for c in claimed)


def _find_hits(text: str, identity: PatientIdentity) -> list[_Hit]:
    terms = _identity_terms(identity)
    claimed = [
        _Hit(m.start(), m.end(), terms[_key(m.group())])
        for m in _identity_regex(terms).finditer(text)
    ]
    for kind, pattern, group in _PATTERNS:
        for m in pattern.finditer(text):
            hit = _Hit(m.start(group), m.end(group), kind)
            if not _overlaps(hit, claimed):
                claimed.append(hit)
    for m in _AGE.finditer(text):
        group = 1 if m.group(1) else 2
        if int(m.group(group)) >= 90:
            hit = _Hit(m.start(group), m.end(group), None, "90+")
            if not _overlaps(hit, claimed):
                claimed.append(hit)
    return sorted(claimed, key=lambda h: h.start)


def redact(text: str, identity: PatientIdentity) -> Redacted:
    """Replace identifiers with `[KIND_n]` tokens; each distinct spelling gets its own token."""
    mapping: dict[str, str] = {}
    by_spelling: dict[tuple[str, str], str] = {}
    counters: dict[str, int] = {}
    out: list[str] = []
    pos = 0
    for hit in _find_hits(text, identity):
        out.append(text[pos : hit.start])
        pos = hit.end
        if hit.kind is None:
            out.append(hit.fixed)
            continue
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
        out.append(token)
    out.append(text[pos:])
    return Redacted("".join(out), mapping)


def restore(text: str, mapping: dict[str, str]) -> str:
    """Put the exact original text back for every known token, in one pass."""
    return _TOKEN_SHAPE.sub(lambda m: mapping.get(m.group(), m.group()), text)
