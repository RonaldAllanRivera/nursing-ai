"""Replacing known identifiers with tokens before the AI sees a note, and putting them back."""

import re
from datetime import date

from hypothesis import assume, given
from hypothesis import strategies as st
from nursing_core.demo import load_demo_cases
from nursing_core.domain.patient import PatientIdentity, Relative
from nursing_core.pipeline.redact import mentions_identity, redact, restore

CASES = load_demo_cases()
PERPETUA = CASES[0].patient
TEODORA = CASES[1].patient
HAROLD = CASES[2].patient


def _identity(**changes: object) -> PatientIdentity:
    base = PatientIdentity(
        given_name="Perpetua",
        middle_name="Qorvanne",
        family_name="Malabanan",
        suffix="Jr",
        nicknames=["Nena"],
        relatives=[Relative(name="Zyxquil Malabanan", relation="son")],
        record_number="SYN-PH-0099",
        birth_date=date(1962, 3, 4),
        address="12 Zyxquil St, Qorvanne",
        postal_code="1234",
    )
    return base.model_copy(update=changes)


def test_names_nicknames_and_relatives_replaced() -> None:
    note = "Teodora Dimaculangan, Lola Dora, anak na si Ramil, Dimaculangan again"
    out = redact(note, TEODORA)
    assert out.text == "[PATIENT_1], [NICKNAME_1], anak na si [RELATIVE_1], [PATIENT_2] again"
    assert out.mapping["[PATIENT_1]"] == "Teodora Dimaculangan"
    assert out.mapping["[RELATIVE_1]"] == "Ramil"


def test_full_name_forms_and_suffix() -> None:
    ident = _identity()
    out = redact("Perpetua Qorvanne Malabanan Jr arrived; Jr alone stays", ident)
    assert out.text == "[PATIENT_1] arrived; Jr alone stays"
    out2 = redact("Perpetua  Malabanan", ident)
    assert out2.text == "[PATIENT_1]"
    assert out2.mapping == {"[PATIENT_1]": "Perpetua  Malabanan"}


def test_record_number_birth_date_and_address_replaced() -> None:
    ident = _identity()
    note = "SYN-PH-0099 born 1962-03-04, 3/4/1962, 04/03/1962, March 4, 1962, 4 Mar 1962."
    note += " Lives at 12 Zyxquil St, Qorvanne 1234."
    out = redact(note, ident)
    assert "[RECORD_NO_1]" in out.text
    assert "[ADDRESS_1]" in out.text
    assert "[POSTAL_CODE_1]" in out.text
    assert out.text.count("[BIRTH_DATE_") == 5
    assert "1962" not in out.text
    assert restore(out.text, out.mapping) == note


def test_name_inside_another_word_is_kept() -> None:
    out = redact("Teodora and Doras, Dora", TEODORA)
    assert out.text == "[PATIENT_1] and Doras, [NICKNAME_1]"
    ana = _identity(given_name="Ana", middle_name=None, family_name="Qorvanne", suffix=None)
    assert redact("banana with Ana", ana).text == "banana with [PATIENT_1]"


def test_us_phone_email_ssn_url_and_ip_replaced() -> None:
    note = (
        "call (415) 555-0134 or 415-555-0134, 415.555.0134, +1 415 555 0134, +14155550134, "
        "0917 555 0134, 09175550134, +63 917 555 0134, (02) 8555 0134, 02-8555-0134. "
        "mail zyx@example.com, SSN 900-12-3456, see https://example.com/a?b=1). "
        "also www.example.com, host 192.0.2.17."
    )
    out = redact(note, PERPETUA)
    assert out.text.count("[PHONE_") == 10
    assert "[EMAIL_1]" in out.text
    assert "[SSN_1]" in out.text
    assert "[URL_1])" in out.text
    assert "[URL_2]," in out.text
    assert "[IP_1]." in out.text
    assert restore(out.text, out.mapping) == note
    assert redact("ID 192.0.2.256", PERPETUA).text == "ID 192.0.2.256"


def test_clinical_numbers_are_never_changed() -> None:
    note = (
        "BP 142/84 pain 6/10 1015 0830 HR 112 T 37.8 IVF #3 0800 D5LR 1L @ 30gtts/min 500mg "
        "Room 412-A SpO2 95% 2L NC A&Ox4 176 lb 2026 1/2 3am 11pm"
    )
    assert redact(note, PERPETUA).text == note


def test_dates_replaced_but_not_scores_or_times() -> None:
    note = (
        "11/12/2026, 11/12/26, 11-12-2026, 2026-11-12, 12 Nov 2026, Nov 12, 2026, "
        "November 12, 12 November"
    )
    out = redact(note, PERPETUA)
    assert out.text.count("[DATE_") == 8
    assert restore(out.text, out.mapping) == note


def test_age_90_and_over_becomes_90_plus() -> None:
    out = redact("91 y/o, 91 yo, 91 y.o., 91-year-old, 91 years old, 91 yrs old, aged 91", PERPETUA)
    assert out.text == (
        "90+ y/o, 90+ yo, 90+ y.o., 90+-year-old, 90+ years old, 90+ yrs old, aged 90+"
    )
    assert out.mapping == {}
    assert restore(out.text, out.mapping) == out.text
    assert redact("89 y/o and 90 y/o", PERPETUA).text == "89 y/o and 90+ y/o"


def test_zip_only_from_record_or_after_state_code() -> None:
    ident = _identity()
    out = redact("0800 IVF #3 CA 94110, DC 20001-9876, rm 55555, 1234", ident)
    assert out.text == "0800 IVF #3 CA [ZIP_1], DC [ZIP_2], rm 55555, [POSTAL_CODE_1]"
    assert out.mapping["[ZIP_2]"] == "20001-9876"


def test_bp_and_pain_scores_are_not_dates() -> None:
    assert redact("BP 142/84, pain 6/10, 1/2", HAROLD).text == "BP 142/84, pain 6/10, 1/2"


def test_spellings_get_their_own_tokens() -> None:
    out = redact("Lola Dora, LOLA DORA, Lola Dora", TEODORA)
    assert out.text == "[NICKNAME_1], [NICKNAME_2], [NICKNAME_1]"
    assert restore(out.text, out.mapping) == "Lola Dora, LOLA DORA, Lola Dora"


def test_literal_token_in_the_note_is_never_rewritten() -> None:
    note = "[PATIENT_1] typed by hand, Teodora"
    out = redact(note, TEODORA)
    assert out.text == "[PATIENT_1] typed by hand, [PATIENT_2]"
    assert restore(out.text, out.mapping) == note


def test_restore_leaves_unknown_tokens_and_does_not_rescan() -> None:
    assert restore("[X_1] [A_1]", {"[A_1]": "[B_1]", "[B_1]": "no"}) == "[X_1] [B_1]"


def test_patient_beats_nickname_beats_relative() -> None:
    ident = _identity(
        given_name="Zyxquil",
        middle_name=None,
        family_name="Qorvanne",
        suffix=None,
        nicknames=["Qorvanne Zed"],
        relatives=[Relative(name="Zed Qorvanne", relation="son")],
    )
    out = redact("Qorvanne, Zed, Qorvanne Zed, Zed Qorvanne", ident)
    assert out.text == "[PATIENT_1], [NICKNAME_1], [NICKNAME_2], [RELATIVE_1]"


def test_mentions_identity_uses_whole_words() -> None:
    assert mentions_identity("saw LOLA dora today", TEODORA)
    assert mentions_identity("TEODORA", TEODORA)
    assert not mentions_identity("Dora on her own", PERPETUA)
    assert mentions_identity("record syn-ph-0012", PERPETUA)
    assert not mentions_identity("Lolas", TEODORA)


def test_redacted_text_mentions_no_identity() -> None:
    for case in CASES:
        out = redact(case.rough_note.text, case.patient)
        assert not mentions_identity(out.text, case.patient)


def _squash(s: str) -> str:
    return re.sub(r"\s+", " ", s)


def test_demo_notes_redact_to_the_tokens_their_model_output_uses() -> None:
    for case in CASES:
        text = _squash(redact(case.rough_note.text, case.patient).text)
        quotes = [
            q
            for entry in case.model_output.entries
            for part in (entry.data, entry.action, entry.response)
            for line in part
            for q in line.source_quotes
        ]
        assert quotes
        for q in quotes:
            assert _squash(q) in text


_IDENTITIES = [PERPETUA, TEODORA, HAROLD, _identity()]
_FRAGMENTS = [
    "BP 142/84",
    "pain 6/10",
    "1015",
    "T 37.8",
    "CA 94110",
    "call 415-555-0134",
    "11/12/2026",
]


def _strings(ident: PatientIdentity) -> list[str]:
    return [
        ident.given_name,
        ident.family_name,
        *ident.nicknames,
        *(r.name for r in ident.relatives),
        *(w for r in ident.relatives for w in r.name.split()),
        ident.record_number,
        ident.birth_date.isoformat(),
    ]


@st.composite
def _notes(draw: st.DrawFn) -> tuple[PatientIdentity, str]:
    ident = draw(st.sampled_from(_IDENTITIES))
    pieces = st.one_of(
        st.sampled_from(_strings(ident)).flatmap(
            lambda s: st.sampled_from([s, s.lower(), s.upper()])
        ),
        st.sampled_from(_FRAGMENTS),
        st.text(max_size=12),
    )
    parts = draw(st.lists(pieces, max_size=8))
    sep = draw(st.sampled_from([" ", "  ", "\n", ", "]))
    return ident, sep.join(parts)


@given(_notes())
def test_restore_undoes_redact(case: tuple[PatientIdentity, str]) -> None:
    ident, note = case
    assume(not re.search(r"(?i)aged|y/o|y\.o|yo|year|yrs", note))
    out = redact(note, ident)
    assert restore(out.text, out.mapping) == note
