"""Replacing known identifiers with tokens before the AI sees a note, and putting them back."""

import re
from datetime import date

import pytest
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
        nicknames=["Qorvy"],
        relatives=[Relative(name="Zyxquil Malabanan", relation="son")],
        record_number="SYN-PH-0099",
        birth_date=date(1962, 3, 4),
        address="12 Vexlor St, Plimth",
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
    note = (
        "SYN-PH-0099 born 1962-03-04, 3/4/1962, 04/03/1962, 3-4-1962, 04-03-1962, "
        "March 4, 1962, Mar 4, 1962, 4 March 1962, 4 Mar 1962."
    )
    note += " Lives at 12 Vexlor St, Plimth 1234."
    out = redact(note, ident)
    assert "[RECORD_NO_1]" in out.text
    assert "[ADDRESS_1]" in out.text
    assert "[POSTAL_CODE_1]" in out.text
    assert out.text.count("[BIRTH_DATE_") == 9
    assert "1962" not in out.text
    assert restore(out.text, out.mapping) == note


def test_name_inside_another_word_is_kept() -> None:
    out = redact("Teodora and Doras, Dora", TEODORA)
    assert out.text == "[PATIENT_1] and Doras, [NICKNAME_1]"
    zyx = _identity(given_name="Zyxquil", middle_name=None, family_name="Qorvanne", suffix=None)
    assert redact("xzyxquil with Zyxquil", zyx).text == "xzyxquil with [PATIENT_1]"


def test_us_phone_email_ssn_url_and_ip_replaced() -> None:
    note = (
        "call (415) 555-0134 or 415-555-0134, 415.555.0134, +1 415 555 0134, +14155550134, "
        "0917 555 0134, 09175550134, +63 917 555 0134, (02) 8555 0134, 02-8555-0134. "
        "mail zyx@example.com, SSN 900-12-3456, see https://example.com/a?b=1). "
        "also www.example.com, host 192.0.2.17."
    )
    out = redact(note, PERPETUA)
    phones = [v for k, v in out.mapping.items() if k.startswith("[PHONE_")]
    assert phones == [
        "(415) 555-0134",
        "415-555-0134",
        "415.555.0134",
        "+1 415 555 0134",
        "+14155550134",
        "0917 555 0134",
        "09175550134",
        "+63 917 555 0134",
        "(02) 8555 0134",
        "02-8555-0134",
    ]
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
    out = redact(note + "; pain 6/10 at 0830 and 1015, BP 142/84", PERPETUA)
    assert out.text.count("[DATE_") == 8
    assert out.text.endswith("; pain 6/10 at 0830 and 1015, BP 142/84")
    assert restore(out.text, out.mapping) == note + "; pain 6/10 at 0830 and 1015, BP 142/84"


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
    out = redact("0800 IVF #3 CA 94110, DC 20001-9876, rm 55555, Plimth 1234", ident)
    assert out.text == "0800 IVF #3 CA [ZIP_1], DC [ZIP_2], rm 55555, Plimth [POSTAL_CODE_1]"
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
        nicknames=["Qorvanne Vexlo"],
        relatives=[Relative(name="Vexlo Qorvanne", relation="son")],
    )
    out = redact("Qorvanne, Vexlo, Qorvanne Vexlo, Vexlo Qorvanne", ident)
    assert out.text == "[PATIENT_1], [NICKNAME_1], [NICKNAME_2], [RELATIVE_1]"


def test_mentions_identity_uses_whole_words() -> None:
    assert mentions_identity("saw LOLA dora today", TEODORA)
    assert mentions_identity("TEODORA", TEODORA)
    assert not mentions_identity("Perpetuas and Malabanans", PERPETUA)
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


@pytest.mark.parametrize(
    "note",
    [
        "pain 6/10 may need PRN",
        "RR 20 may need O2",
        "RR 20 May need O2",
        "pain dec 4/10",
        "pain Dec 4/10",
        "UO DEC 30 mL/hr",
        "may 4, 2026 is lower case",
    ],
)
def test_month_words_never_swallow_clinical_numbers(note: str) -> None:
    assert redact(note, PERPETUA).text == note


@pytest.mark.parametrize(
    "note",
    ["Nov 12", "NOV 12 2026", "November 12", "12 NOVEMBER", "May 4, 2026", "4 Sept", "12 NOV 2026"],
)
def test_month_name_dates_are_redacted(note: str) -> None:
    out = redact(f"seen {note} ok", PERPETUA)
    assert out.text == "seen [DATE_1] ok"
    assert out.mapping == {"[DATE_1]": note}
    punctuated = redact(f"seen {note}.", PERPETUA)
    assert punctuated.text == "seen [DATE_1]."


def test_a_title_case_date_with_a_bare_year_keeps_the_year_rule() -> None:
    assert redact("seen 12 Nov 2026.", PERPETUA).text == "seen [DATE_1]."
    assert redact("seen 12 Nov 2026 ok", PERPETUA).text == "seen [DATE_1] 2026 ok"
    assert redact("May 4 2026 VS taken", PERPETUA).text == "[DATE_1] VS taken"
    assert redact("MAY 4 20 VS taken", PERPETUA).text == "MAY 4 20 VS taken"


def test_a_name_glued_to_a_date_ssn_or_digits_is_still_redacted() -> None:
    out = redact("Teodora2026-11-12 seen, Ramil900-12-3456, Ramil11/12/2026, x9Dora", TEODORA)
    assert (
        out.text
        == "[PATIENT_1][DATE_1] seen, [RELATIVE_1][SSN_1], [RELATIVE_1][DATE_2], x9[NICKNAME_1]"
    )
    assert restore(out.text, out.mapping) == (
        "Teodora2026-11-12 seen, Ramil900-12-3456, Ramil11/12/2026, x9Dora"
    )
    assert mentions_identity("Teodora2026-11-12", TEODORA)
    assert not mentions_identity("Teodoras2026", TEODORA)


def test_odd_letters_never_crash_and_still_match() -> None:
    ident = _identity(given_name="Zyxquils", middle_name=None, family_name="Qorvanne", suffix=None)
    assert redact("ZYXQUIL\u017f note", ident).text == "[PATIENT_1] note"
    assert redact("Zyxqu\u0130ls note", ident).text == "[PATIENT_1] note"
    assert mentions_identity("ZYXQUIL\u017f", ident)


def test_accents_are_ignored_when_matching_names() -> None:
    ident = _identity(given_name="Qorvane", middle_name=None, family_name="Vexlor", suffix=None)
    out = redact("Qorva\u00f1e, QORVA\u00d1E, qorvane, Qorvan\u0303e, Qorvanes", ident)
    assert out.text == "[PATIENT_1], [PATIENT_2], [PATIENT_3], [PATIENT_4], Qorvanes"
    assert out.mapping["[PATIENT_4]"] == "Qorvan\u0303e"
    assert restore(out.text, out.mapping) == (
        "Qorva\u00f1e, QORVA\u00d1E, qorvane, Qorvan\u0303e, Qorvanes"
    )
    accented = _identity(
        given_name="Qorva\u00f1e", middle_name=None, family_name="Vexlor", suffix=None
    )
    assert redact("qorvane", accented).text == "[PATIENT_1]"
    assert mentions_identity("QORVANE", accented)


def test_a_mark_after_a_name_is_covered_with_it() -> None:
    ident = _identity(given_name="Qorvane", middle_name=None, family_name="Vexlor", suffix=None)
    out = redact("Qorvane\u0301 ok", ident)
    assert out.text == "[PATIENT_1] ok"
    assert out.mapping == {"[PATIENT_1]": "Qorvane\u0301"}


def test_a_two_word_given_name_is_matched_whole() -> None:
    ident = _identity(given_name="Zyx Quil", middle_name=None, family_name="Qorvanne", suffix=None)
    assert redact("Zyx   Quil, Zyx, Quil", ident).text == "[PATIENT_1], [PATIENT_2], [PATIENT_3]"


def test_name_words_split_on_hyphens_and_apostrophes() -> None:
    ident = _identity(
        given_name="Zyx-Quil", middle_name=None, family_name="O'Qorvanne", suffix=None
    )
    out = redact("Zyx-Quil, Quil, Zyx, O'Qorvanne, Qorvanne, O, Q-Zyx", ident)
    assert (
        out.text
        == "[PATIENT_1], [PATIENT_2], [PATIENT_3], [PATIENT_4], [PATIENT_5], O, Q-[PATIENT_3]"
    )


def test_overlapping_hits_merge_into_one_span() -> None:
    url = "https://example.com/teodora/123456"
    out = redact(f"see {url} now", TEODORA)
    assert out.text == "see [URL_1] now"
    assert out.mapping == {"[URL_1]": url}
    mail = redact("teodora@example.com", TEODORA)
    assert mail.text == "[EMAIL_1]"
    # a name that only partly overlaps a longer pattern never leaves characters behind
    out = redact("Ramil 2026-11-12 Dimaculangan2026-11-12", TEODORA)
    assert out.text == "[RELATIVE_1] [DATE_1] [PATIENT_1][DATE_1]"
    record = _identity(record_number="SYN-2026")
    both = redact("SYN-2026-11-12", record)
    assert both.text == "[DATE_1]"
    assert both.mapping == {"[DATE_1]": "SYN-2026-11-12"}
    assert restore(both.text, both.mapping) == "SYN-2026-11-12"
    assert not mentions_identity(both.text, record)


def test_a_digit_postal_code_needs_address_context() -> None:
    ident = _identity(postal_code="1200")
    note = "1200 VS taken, IVF 1200 mL, Plimth 1200, zip: 1200, Postal Code 1200, TX, 1200"
    out = redact(note, ident)
    assert out.text == (
        "1200 VS taken, IVF 1200 mL, Plimth [POSTAL_CODE_1], zip: [POSTAL_CODE_1], "
        "Postal Code [POSTAL_CODE_1], TX, [POSTAL_CODE_1]"
    )
    assert redact("Plimth\n1200", ident).text == "Plimth\n1200"
    assert redact("tx 1200 and in 1200", ident).text == "tx 1200 and in 1200"
    assert mentions_identity("Plimth 1200", ident)
    assert not mentions_identity("IVF 1200 mL", ident)


def test_a_postal_code_with_a_letter_is_redacted_anywhere() -> None:
    ident = _identity(postal_code="K1A 0B1")
    assert redact("sent to K1A 0B1.", ident).text == "sent to [POSTAL_CODE_1]."
    assert mentions_identity("k1a  0b1", ident)


def test_state_code_zip_skips_everyday_clinical_abbreviations() -> None:
    note = "heparin SC 10000 units, IN 12000 mL, NC 20000, OR 97201, PA 15213, CT 06101"
    assert redact(note, PERPETUA).text == note
    assert redact("CA 94110, TX 75001, NY 10001-1234", PERPETUA).text == (
        "CA [ZIP_1], TX [ZIP_2], NY [ZIP_3]"
    )


def test_urls_in_capitals_and_spaced_us_phone_are_redacted() -> None:
    out = redact("HTTPS://EXAMPLE.COM/X, WWW.EXAMPLE.COM, Tel: 415 555 0134", PERPETUA)
    assert out.text == "[URL_1], [URL_2], Tel: [PHONE_1]"
    assert out.mapping["[PHONE_1]"] == "415 555 0134"
    assert redact("range 555-0134 and 1000 500 100", PERPETUA).text == (
        "range 555-0134 and 1000 500 100"
    )


def test_more_age_forms_become_90_plus() -> None:
    note = "91 y.o F, age 91, 91 years old, 91 years of age, 91 yrs, 91F, age 89, 5 yrs"
    assert redact(note, PERPETUA).text == (
        "90+ y.o F, age 90+, 90+ years old, 90+ years of age, 90+ yrs, 91F, age 89, 5 yrs"
    )


_IDENTITIES = [PERPETUA, TEODORA, HAROLD, _identity(postal_code="1200")]
_FRAGMENTS = [
    "BP 142/84",
    "pain 6/10",
    "1015",
    "T 37.8",
    "CA 94110",
    "call 415-555-0134",
    "11/12/2026",
    "Nov 12",
    "IVF 1200 mL",
    "[PATIENT_1]",
    "[DATE_2]",
    "https://example.com/zyxquil/9",
    "zip 1200",
    "Plimth 1200",
    "3/4/1962",
    "Mar 4, 1962",
    "4 March 1962",
    "900-12-3456",
]
_SEPARATORS = ["", " ", "  ", "\n", ", "]


def _strings(ident: PatientIdentity) -> list[str]:
    full = f"{ident.given_name} {ident.family_name}"
    return [
        f"{full} {ident.suffix}" if ident.suffix else full,
        ident.suffix or ident.family_name,
        ident.given_name,
        ident.middle_name or ident.given_name,
        ident.family_name,
        *ident.nicknames,
        *(r.name for r in ident.relatives),
        *(w for r in ident.relatives for w in r.name.split()),
        ident.record_number,
        ident.address or ident.given_name,
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
    return ident, draw(st.sampled_from(_SEPARATORS)).join(parts)


@given(_notes())
def test_restore_undoes_redact(case: tuple[PatientIdentity, str]) -> None:
    ident, note = case
    assume(not re.search(r"(?i)age|y/o|y\.o|yo|year|yrs", note))
    out = redact(note, ident)
    assert restore(out.text, out.mapping) == note


@given(_notes())
def test_no_identity_string_survives_redaction(case: tuple[PatientIdentity, str]) -> None:
    ident, note = case
    assert not mentions_identity(redact(note, ident).text, ident)


@given(st.text())
def test_redact_never_raises_on_arbitrary_text(note: str) -> None:
    out = redact(note, _identity())
    assert not mentions_identity(out.text, _identity())


@pytest.mark.parametrize(
    ("postal", "note"),
    [
        ("1200", "IN 12000 mL"),
        ("1000", "heparin SC 10000 units"),
        ("5000", "heparin SC 5000 units"),
        ("1000", "IN 1000 mL OUT 400 mL"),
        ("1200", "2L NC, 1200 VS stable"),
        ("1200", "OR 1200 mL, PA 1200"),
    ],
)
def test_a_record_postal_code_never_changes_a_dose_or_volume(postal: str, note: str) -> None:
    ident = _identity(postal_code=postal)
    assert redact(note, ident).text == note
    assert not mentions_identity(note, ident)


def test_a_digit_edged_term_never_matches_inside_a_longer_number() -> None:
    ident = _identity(record_number="4411", postal_code="1200")
    note = "ref 14411 and 44110 and zip 12001 but 4411 and zip 1200"
    assert redact(note, ident).text == (
        "ref 14411 and 44110 and zip 12001 but [RECORD_NO_1] and zip [POSTAL_CODE_1]"
    )


def test_terms_with_nothing_to_match_are_dropped() -> None:
    ident = _identity(
        record_number="-", address=".", postal_code=" ", nicknames=["\u0301", "-"]
    ).model_copy(update={"given_name": "\u0301", "family_name": "\u00ad"})
    assert redact("a - . \u0301 b", ident).text == "a - . \u0301 b"
    assert not mentions_identity("a - . b", ident)


def test_redaction_repeats_until_no_known_name_is_left() -> None:
    ident = _identity(given_name="Qorv\u00e9", middle_name=None, family_name="Vexlor", suffix=None)
    out = redact("Qorv\u00e9zyx@example.com", ident)
    assert out.text == "[PATIENT_1][EMAIL_1]"
    assert restore(out.text, out.mapping) == "Qorv\u00e9zyx@example.com"
    assert not mentions_identity(out.text, ident)


def test_token_shaped_text_never_matches_a_name() -> None:
    ident = _identity(given_name="Date", middle_name=None, family_name="Vexlor", suffix=None)
    note = "[DATE_1] and [PATIENT_1] seen Date, 2026-11-12"
    out = redact(note, ident)
    assert out.text == "[DATE_1] and [PATIENT_1] seen [PATIENT_2], [DATE_2]"
    assert restore(out.text, out.mapping) == note
    assert not mentions_identity("[DATE_1]", ident)
    assert mentions_identity("Date", ident)


def test_an_invisible_format_character_inside_a_name_does_not_hide_it() -> None:
    out = redact("Teo\u00addora and Teo\u200bdora", TEODORA)
    assert out.text == "[PATIENT_1] and [PATIENT_2]"
    assert out.mapping["[PATIENT_1]"] == "Teo\u00addora"
    assert mentions_identity("Teo\u00addora", TEODORA)


@pytest.mark.parametrize(
    "note",
    [
        "PO 360 240 1200 mL",
        "I&O 240 120 1000",
        "HR 112 108 1040",
        "q4 100 120 1400",
        "555-0134",
    ],
)
def test_spaced_numbers_are_not_phones_without_a_phone_cue(note: str) -> None:
    assert redact(note, PERPETUA).text == note


@pytest.mark.parametrize(
    "cue", ["Tel", "tel.", "Phone:", "ph", "Mobile:", "cell", "Contact", "call"]
)
def test_spaced_phone_after_a_phone_cue_is_redacted(cue: str) -> None:
    out = redact(f"{cue} 415 555 0134 ok", PERPETUA)
    assert out.text == f"{cue} [PHONE_1] ok"
    assert out.mapping == {"[PHONE_1]": "415 555 0134"}


@pytest.mark.parametrize(
    "note", ["T 38.1 Dec to 37.5", "Hgb 10.4 Dec", "UO Dec 30.5 mL", "Dec 4.5 mL"]
)
def test_a_day_number_inside_a_decimal_is_not_a_date(note: str) -> None:
    assert redact(note, PERPETUA).text == note


def test_a_year_after_month_and_day_needs_a_comma_or_a_clean_end() -> None:
    assert redact("Nov 12 2030 VS taken", PERPETUA).text == "[DATE_1] 2030 VS taken"
    assert redact("Dec 4 2000 mL", PERPETUA).text == "[DATE_1] 2000 mL"
    assert redact("Nov 12, 2030 VS", PERPETUA).text == "[DATE_1] VS"
    assert redact("12 Nov 2026.", PERPETUA).text == "[DATE_1]."
    assert redact("12 Nov 2026\nnext", PERPETUA).text == "[DATE_1]\nnext"
    assert redact("12 Nov 2026 ", PERPETUA).text == "[DATE_1] "


def test_age_after_a_label_with_a_colon() -> None:
    assert redact("Age: 91, age:92, Aged: 93", PERPETUA).text == "Age: 90+, age:90+, Aged: 90+"


def test_a_term_ending_in_punctuation_matches_next_to_anything() -> None:
    ident = _identity(address="Vexlor St, Plimth.")
    assert redact("at Vexlor St, Plimth.ok", ident).text == "at [ADDRESS_1]ok"


@pytest.mark.parametrize("note", ["[TEODORA_1]", "[RAMIL_1] at bedside", "[teodora_1]"])
def test_only_real_token_kinds_are_masked(note: str) -> None:
    out = redact(note, TEODORA)
    assert "Teodora" not in out.text.title()
    assert not mentions_identity(out.text, TEODORA)
    assert mentions_identity(note, TEODORA)
    assert restore(out.text, out.mapping) == note


def test_phone_glued_to_a_name_is_redacted_after_the_name_is_replaced() -> None:
    out = redact("Ramil415-555-0134 and Ramil09175550134", TEODORA)
    assert out.text == "[RELATIVE_1][PHONE_1] and [RELATIVE_1][PHONE_2]"
    assert restore(out.text, out.mapping) == "Ramil415-555-0134 and Ramil09175550134"


def test_a_typed_token_next_to_a_phone_is_left_alone() -> None:
    note = "Ramil[PHONE_1]415-555-0134"
    out = redact(note, TEODORA)
    assert out.text == "[RELATIVE_1][PHONE_1][PHONE_2]"
    assert out.mapping["[PHONE_2]"] == "415-555-0134"
    assert restore(out.text, out.mapping) == note


@pytest.mark.parametrize(
    "note",
    ["Teodora\u200bRamil", "Dora\u00adTeodora", "Ramil\u2060Dimaculangan", "Ramil\u200d\u200bDora"],
)
def test_two_names_joined_by_an_invisible_character_are_both_redacted(note: str) -> None:
    out = redact(note, TEODORA)
    assert "[" in out.text
    assert not mentions_identity(out.text, TEODORA)
    assert restore(out.text, out.mapping) == note


@pytest.mark.parametrize(
    "cue", ["Phone number:", "Tel no.", "Contact #:", "tel number", "Mobile No:", "cell #"]
)
def test_the_phone_cue_may_carry_no_number_or_hash(cue: str) -> None:
    out = redact(f"{cue} 415 555 0134 ok", PERPETUA)
    assert out.text == f"{cue} [PHONE_1] ok"


def test_a_spaced_ph_number_needs_a_mobile_prefix() -> None:
    assert redact("0800 240 1200 mL", PERPETUA).text == "0800 240 1200 mL"
    assert redact("call 0917 555 0134", PERPETUA).text == "call [PHONE_1]"
    assert redact("0917 555 0134", PERPETUA).text == "[PHONE_1]"


@pytest.mark.parametrize(
    "note",
    ["PIV age: 96 hrs", "line age 96 hrs", "age 96 hours", "age 120 days", "age 96 h", "age 96 h."],
)
def test_age_followed_by_a_duration_is_not_an_age(note: str) -> None:
    assert redact(note, PERPETUA).text == note


@pytest.mark.parametrize(
    ("note", "expected"),
    [
        ("Age: 91 h/o HTN", "Age: 90+ h/o HTN"),
        ("age 91 d/c", "age 90+ d/c"),
        ("aged 91 d/t fall", "aged 90+ d/t fall"),
        ("aged 91 h.o. CHF", "aged 90+ h.o. CHF"),
    ],
)
def test_an_age_before_a_one_letter_shorthand_still_becomes_90_plus(
    note: str, expected: str
) -> None:
    assert redact(note, PERPETUA).text == expected


def test_age_labels_still_redact_without_a_duration() -> None:
    assert (
        redact("Age: 91, age 91, age 91 years", PERPETUA).text == "Age: 90+, age 90+, age 90+ years"
    )


def test_later_pass_tokens_skip_numbers_typed_in_the_original_note() -> None:
    ident = _identity(given_name="Qorv\u00e9", middle_name=None, family_name="Vexlor", suffix=None)
    note = "Qorv\u00e9zyx@example.com https://example.com/[PATIENT_1]"
    out = redact(note, ident)
    assert out.text == "[PATIENT_2][EMAIL_1] [URL_1]"
    assert restore(out.text, out.mapping) == note


@pytest.mark.parametrize(
    "note",
    [
        "Tel. no. 415 555 0134",
        "phone: no. 415 555 0134",
        "son's number: 415 555 0134",
        "Ramil (son) tel 415 555 0134",
        "Contact: Ramil (son), 415 555 0134",
    ],
)
def test_a_phone_cue_with_a_full_stop_or_earlier_on_the_line_counts(note: str) -> None:
    out = redact(note, TEODORA)
    assert "415 555 0134" not in out.text
    assert "415 555 0134" in out.mapping.values()
    assert restore(out.text, out.mapping) == note


def test_every_spaced_phone_after_a_cue_on_its_line_is_redacted() -> None:
    note = "tel 415 555 0134 or 415 555 0199\nI&O 240 120 1000"
    out = redact(note, PERPETUA)
    assert out.text == "tel [PHONE_1] or [PHONE_2]\nI&O 240 120 1000"


def _without_tokens(text: str) -> str:
    return re.sub(r"\[[A-Z_]+_\d+\]", "", text)


def test_redaction_keeps_going_until_a_long_chain_of_glued_identifiers_is_gone() -> None:
    probe = "Ramil415-555-0134Nov 12+63 917 555 0134Dec 4 +1 415 555 0199Jan 5+1 415 555 0199"
    longer = "Ramil" + "".join(f"+1 415 555 01{n:02d}Jan {n + 1}" for n in range(10))
    for note in (probe, longer):
        out = redact(note, TEODORA)
        assert "555" not in _without_tokens(out.text), out.text
        assert not mentions_identity(out.text, TEODORA)
        assert restore(out.text, out.mapping) == note


@pytest.mark.parametrize(
    ("note", "kind", "original"),
    [
        ("seen 11.12.2026 ok", "DATE", "11.12.2026"),
        ("seen 2026/11/12 ok", "DATE", "2026/11/12"),
        ("seen 12th of November ok", "DATE", "12th of November"),
        ("seen November 12th ok", "DATE", "November 12th"),
        ("SSN 900123456 ok", "SSN", "900123456"),
        ("SSN: 900123456 ok", "SSN", "900123456"),
        ("tel 8555 0134 ok", "PHONE", "8555 0134"),
        ("Tel. no. 8555 0134 ok", "PHONE", "8555 0134"),
    ],
)
def test_more_date_ssn_and_landline_shapes_are_redacted(
    note: str, kind: str, original: str
) -> None:
    out = redact(note, PERPETUA)
    assert out.mapping == {f"[{kind}_1]": original}
    assert out.text == note.replace(original, f"[{kind}_1]")


@pytest.mark.parametrize(
    "note",
    [
        "Hgb 11.12 g/dL, plt 2026",
        "VS at 0800 1200 1600",
        "call bell within reach, VS 0800 1200",
        "BP 120/80/60, 1999/13/40",
        "ref 900123456 and 11.12.20261",
    ],
)
def test_new_date_ssn_and_landline_shapes_leave_clinical_numbers_alone(note: str) -> None:
    assert redact(note, PERPETUA).text == note
