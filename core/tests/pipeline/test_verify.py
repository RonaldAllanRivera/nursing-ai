"""Deciding each line's status from its quotes, numbers and units."""

from hypothesis import given
from hypothesis import strategies as st
from nursing_core.demo import DEMO_FACILITIES, load_demo_cases
from nursing_core.domain.model_output import ModelLine
from nursing_core.domain.notes import (
    DraftLine,
    FdarSection,
    LineReview,
    LineStatus,
    MismatchKind,
    Span,
)
from nursing_core.domain.units import Ucum, UnitDefaults
from nursing_core.pipeline.redact import redact, restore
from nursing_core.pipeline.text import prepare
from nursing_core.pipeline.verify import check_line, default_unit, recheck_line, restore_line

PH = UnitDefaults(temperature=Ucum.CEL, weight=None, volume=Ucum.ML)
US = UnitDefaults(temperature=Ucum.DEG_F, weight=None, volume=Ucum.ML)
US_LB = UnitDefaults(temperature=Ucum.DEG_F, weight=Ucum.LB, volume=Ucum.ML)


def _check(
    note: str,
    text: str,
    quotes: list[str],
    *,
    own: bool = False,
    units: UnitDefaults = PH,
) -> DraftLine:
    model_line = ModelLine(text=text, source_quotes=quotes, own_wording=own)
    return check_line("l1", FdarSection.DATA, model_line, prepare(note), units)


def test_quote_found_and_numbers_match_is_source_found() -> None:
    line = _check("pt dizzy since 2 AM, BP 90/60", "BP 90/60.", ["BP 90/60"])
    assert line.status is LineStatus.SOURCE_FOUND
    assert line.number_mismatches == []
    assert line.review is LineReview.PENDING
    assert line.id == "l1"
    assert line.section is FdarSection.DATA
    assert line.text == line.ai_text == "BP 90/60."
    assert line.source_quotes[0].text == "BP 90/60"
    assert line.source_quotes[0].span == Span(start=21, end=29)


def test_own_wording_with_found_quotes_is_summary() -> None:
    line = _check("pt dizzy since 2 AM", "Dizziness.", ["pt dizzy"], own=True)
    assert line.status is LineStatus.SUMMARY


def test_wrong_number_is_number_mismatch() -> None:
    line = _check("RR 18 calm", "RR 20.", ["RR 18"])
    assert line.status is LineStatus.NUMBER_MISMATCH
    [mismatch] = line.number_mismatches
    assert mismatch.kind is MismatchKind.VALUE
    assert mismatch.draft_text == "20"
    assert mismatch.draft_span == Span(start=3, end=5)
    assert (mismatch.note_text, mismatch.note_span) == ("18", Span(start=3, end=5))


def test_quote_not_in_note_is_no_source() -> None:
    line = _check("pt dizzy", "Vomiting.", ["pt vomited"])
    assert line.status is LineStatus.NO_SOURCE
    assert line.source_quotes[0].span is None


def test_line_without_quotes_is_no_source() -> None:
    line = _check("pt dizzy", "Physician notified.", [])
    assert line.status is LineStatus.NO_SOURCE


def test_own_wording_without_quotes_is_summary() -> None:
    line = _check("pt dizzy", "Dizziness.", [], own=True)
    assert line.status is LineStatus.SUMMARY


def test_no_source_beats_number_mismatch() -> None:
    line = _check("RR 18 calm", "RR 20, vomited 3 times.", ["RR 18", "vomited 3 times"])
    assert line.status is LineStatus.NO_SOURCE
    assert line.number_mismatches == []


def test_summary_with_a_wrong_number_is_number_mismatch() -> None:
    line = _check("RR 18 calm", "Breathing at 20.", ["RR 18"], own=True)
    assert line.status is LineStatus.NUMBER_MISMATCH


def test_mismatch_pairs_by_label() -> None:
    note = "BP 90/60 HR 112"
    line = _check(note, "BP 90/60 mmHg, HR 121 bpm.", ["BP 90/60 HR 112"])
    [mismatch] = line.number_mismatches
    assert mismatch.kind is MismatchKind.VALUE
    assert (mismatch.draft_text, mismatch.draft_span) == ("121", Span(start=18, end=21))
    assert (mismatch.note_text, mismatch.note_span) == ("112", Span(start=12, end=15))


def test_mismatch_pairs_by_label_with_a_colon_and_digits_in_the_label() -> None:
    line = _check("hr: 80 spo2=96", "SpO2 : 91.", ["hr: 80 spo2=96"])
    [mismatch] = line.number_mismatches
    assert (mismatch.note_text, mismatch.note_span) == ("96", Span(start=12, end=14))


def test_mismatch_without_a_matching_label_has_no_note_side() -> None:
    line = _check("HR 112 and 3 stools", "Temp 38.", ["HR 112", "3 stools"])
    [mismatch] = line.number_mismatches
    assert (mismatch.note_text, mismatch.note_span) == (None, None)
    line = _check("112 bpm", "HR 121.", ["112 bpm"])
    assert line.number_mismatches[0].note_text is None
    line = _check("HR 112", "121 bpm.", ["HR 112"])
    assert line.number_mismatches[0].note_text is None


def test_label_must_be_a_whole_word() -> None:
    line = _check("CHR 112", "HR 121.", ["CHR 112"])
    assert line.number_mismatches[0].note_text is None


def test_number_compared_by_value() -> None:
    line = _check("temp 37.90 at 0330", "Temp 37.9 at 330.", ["temp 37.90 at 0330"])
    assert line.status is LineStatus.SOURCE_FOUND


def test_edit_that_fixes_the_number_is_source_found_and_edited() -> None:
    note = prepare("RR 18 calm")
    line = check_line(
        "l1",
        FdarSection.DATA,
        ModelLine(text="RR 20.", source_quotes=["RR 18"], own_wording=False),
        note,
        PH,
    )
    edited = recheck_line(line, "RR 18, calm.", note, PH)
    assert edited.status is LineStatus.SOURCE_FOUND
    assert edited.number_mismatches == []
    assert edited.review is LineReview.EDITED
    assert edited.text == "RR 18, calm."
    assert edited.ai_text == "RR 20."
    assert edited.source_quotes == line.source_quotes


def test_edit_is_the_nurses_own_words_not_ai_wording() -> None:
    note = prepare("pt dizzy")
    line = _check("pt dizzy", "Dizziness.", ["pt dizzy"], own=True)
    assert line.status is LineStatus.SUMMARY
    assert recheck_line(line, "Dizzy.", note, PH).status is LineStatus.SOURCE_FOUND


def test_edit_that_fixes_one_of_two_numbers_keeps_the_other_marked_in_the_new_text() -> None:
    # The edit fixes the first number and changes the line's length, so the second mismatch's
    # old draft span no longer points at its number: the re-check must find it again.
    note = prepare("HR 112 BP 130/80 resting")
    line = check_line(
        "l1",
        FdarSection.DATA,
        ModelLine(text="HR 121, BP 140/80.", source_quotes=["HR 112 BP 130/80"], own_wording=False),
        note,
        PH,
    )
    assert [m.draft_text for m in line.number_mismatches] == ["121", "140/80"]
    new_text = "Heart rate 112 bpm, BP 140/80."
    edited = recheck_line(line, new_text, note, PH)
    assert edited.status is LineStatus.NUMBER_MISMATCH
    [left] = edited.number_mismatches
    assert (left.draft_text, left.note_text) == ("140/80", "130/80")
    assert left.draft_span is not None
    assert new_text[left.draft_span.start : left.draft_span.end] == "140/80"


def test_ph_temperature_without_unit_may_be_celsius() -> None:
    line = _check("BT 37.4 at 3 AM", "Temperature 37.4 °C.", ["BT 37.4"])
    assert line.status is LineStatus.SOURCE_FOUND


def test_ph_temperature_written_as_fahrenheit_is_unit_mismatch() -> None:
    line = _check("BT 37.4 at 3 AM", "Temperature 37.4 °F.", ["BT 37.4"])
    assert line.status is LineStatus.NUMBER_MISMATCH
    [mismatch] = line.number_mismatches
    assert mismatch.kind is MismatchKind.UNIT
    assert (mismatch.draft_text, mismatch.draft_span) == ("37.4 °F", Span(start=12, end=19))
    assert (mismatch.note_text, mismatch.note_span) == ("37.4", Span(start=3, end=7))


def test_cc_and_ml_are_one_unit() -> None:
    line = _check("drank 600cc", "Drank 600 mL.", ["drank 600cc"])
    assert line.status is LineStatus.SOURCE_FOUND


def test_a_different_written_unit_is_unit_mismatch_and_pairs_with_its_unit() -> None:
    line = _check("T 37.4 C, later T 37.4", "T 37.4 F.", ["T 37.4 C, later T 37.4"], units=PH)
    [mismatch] = line.number_mismatches
    assert mismatch.draft_text == "37.4 F"
    assert (mismatch.note_text, mismatch.note_span) == ("37.4 C", Span(start=2, end=8))


def test_us_fahrenheit_kept_passes() -> None:
    line = _check("T 100.2F at noon", "T 100.2 °F.", ["T 100.2F"], units=US)
    assert line.status is LineStatus.SOURCE_FOUND


def test_us_default_fahrenheit_without_a_written_unit_passes() -> None:
    line = _check("T 100.2 at noon", "T 100.2 °F.", ["T 100.2"], units=US)
    assert line.status is LineStatus.SOURCE_FOUND


def test_weight_unit_the_nurse_did_not_write_is_flagged_in_the_us() -> None:
    line = _check("wt 176 this am", "Weight 176 lb.", ["wt 176"], units=US)
    [mismatch] = line.number_mismatches
    assert mismatch.kind is MismatchKind.UNIT
    assert (mismatch.draft_text, mismatch.note_text) == ("176 lb", "176")
    assert (
        _check("wt 176 this am", "Weight 176 lb.", ["wt 176"], units=US_LB).number_mismatches == []
    )
    assert _check("wt 176 lb", "Weight 176 lb.", ["wt 176 lb"], units=US).number_mismatches == []


def test_converted_number_is_value_mismatch() -> None:
    line = _check("T 37.4", "T 99.3 °F.", ["T 37.4"])
    [mismatch] = line.number_mismatches
    assert mismatch.kind is MismatchKind.VALUE
    assert mismatch.draft_text == "99.3"


def test_number_folded_by_normalisation_is_still_a_mismatch() -> None:
    line = _check("pt took ½ tab", "2 tab given", ["2 tab"])
    assert line.source_quotes[0].span is not None
    [mismatch] = line.number_mismatches
    assert mismatch.kind is MismatchKind.VALUE
    assert mismatch.draft_text == "2"
    assert line.status is LineStatus.NUMBER_MISMATCH
    line = _check("wbc 10³ cells", "WBC 103 cells.", ["103 cells"])
    assert line.source_quotes[0].span is not None
    assert line.status is LineStatus.NUMBER_MISMATCH
    assert line.number_mismatches[0].draft_text == "103"


def test_a_number_outside_the_found_quotes_does_not_count() -> None:
    line = _check("RR 18 and HR 90", "HR 90.", ["RR 18"])
    assert line.status is LineStatus.NUMBER_MISMATCH


def test_restore_puts_back_the_ai_text_pending() -> None:
    note = prepare("RR 18 calm")
    line = _check("RR 18 calm", "RR 20.", ["RR 18"])
    edited = recheck_line(line, "RR 18.", note, PH)
    restored = restore_line(edited, note, PH)
    assert restored.text == "RR 20."
    assert restored.review is LineReview.PENDING
    assert restored.status is LineStatus.NUMBER_MISMATCH
    assert restored == line


def test_restore_takes_the_cautious_reading() -> None:
    note = prepare("pt dizzy")
    line = _check("pt dizzy", "Dizziness.", ["pt dizzy"], own=True)
    edited = recheck_line(line, "Dizzy.", note, PH)
    assert edited.status is LineStatus.SOURCE_FOUND
    assert restore_line(edited, note, PH).status is LineStatus.SUMMARY
    assert restore_line(edited, note, PH).text == "Dizziness."
    plain = _check("pt dizzy", "Dizzy.", ["pt dizzy"])
    assert restore_line(plain, note, PH).status is LineStatus.SUMMARY


def test_restore_keeps_the_mismatches_of_the_cautious_reading() -> None:
    note = prepare("RR 18 calm")
    line = _check("RR 18 calm", "RR 20.", ["RR 18"], own=True)
    assert restore_line(line, note, PH).number_mismatches == line.number_mismatches


def test_demo_lines_check_to_their_expected_lines() -> None:
    facilities = {facility.key: facility for facility in DEMO_FACILITIES}
    cases = load_demo_cases()
    assert cases
    for case in cases:
        units = facilities[case.facility_key].units
        mapping = redact(case.rough_note.text, case.patient).mapping
        note = prepare(case.rough_note.text)
        assert len(case.model_output.entries) == len(case.expected_draft.entries)
        for model_entry, expected_entry in zip(
            case.model_output.entries, case.expected_draft.entries, strict=True
        ):
            model_lines = [
                model_entry.focus,
                *model_entry.data,
                *model_entry.action,
                *model_entry.response,
            ]
            expected_lines = list(expected_entry.lines())
            assert len(model_lines) == len(expected_lines)
            for model_line, expected in zip(model_lines, expected_lines, strict=True):
                restored = ModelLine(
                    text=restore(model_line.text, mapping),
                    source_quotes=[restore(q, mapping) for q in model_line.source_quotes],
                    own_wording=model_line.own_wording,
                )
                assert (
                    check_line(expected.id, expected.section, restored, note, units) == expected
                ), (
                    case.key,
                    expected.id,
                )


def _kinds(line: DraftLine) -> list[MismatchKind]:
    return [m.kind for m in line.number_mismatches]


def test_a_dose_fraction_is_not_matched_by_one_of_its_digits() -> None:
    line = _check("gave 1/2 tab PO", "Gave 2 tabs PO.", ["gave 1/2 tab PO"])
    assert line.status is LineStatus.NUMBER_MISMATCH
    assert _kinds(line) == [MismatchKind.VALUE]
    assert line.number_mismatches[0].note_text == "1/2"


def test_a_leading_dot_decimal_is_not_matched_by_a_whole_number() -> None:
    line = _check("lorazepam .5 mg IV", "Lorazepam 5 mg IV given.", ["lorazepam .5 mg IV"])
    assert _kinds(line) == [MismatchKind.VALUE]
    ok = _check("lorazepam .5 mg IV", "Lorazepam 0.50 mg IV given.", ["lorazepam .5 mg IV"])
    assert ok.status is LineStatus.SOURCE_FOUND


def test_digits_inside_a_word_are_not_a_number_to_match() -> None:
    line = _check("D5LR running", "5 units insulin given, D5LR running.", ["D5LR running"])
    assert _kinds(line) == [MismatchKind.VALUE]
    assert line.number_mismatches[0].draft_text == "5"
    ok = _check("D5LR running", "D5LR running.", ["D5LR running"])
    assert ok.status is LineStatus.SOURCE_FOUND


def test_a_number_glued_to_a_label_still_counts() -> None:
    line = _check("HR120 SpO2 95", "HR 120, SpO2 95.", ["HR120 SpO2 95"])
    assert line.status is LineStatus.SOURCE_FOUND


def test_a_draft_vulgar_fraction_is_a_number_to_check() -> None:
    line = _check("gave 1 tab", "Gave ½ tab.", ["gave 1 tab"])
    assert line.status is LineStatus.NUMBER_MISMATCH
    [mismatch] = line.number_mismatches
    assert mismatch.kind is MismatchKind.VALUE
    assert (mismatch.draft_text, mismatch.draft_span) == ("½", Span(start=5, end=6))
    assert (mismatch.note_text, mismatch.note_span) == ("1", Span(start=5, end=6))


def test_a_vulgar_fraction_matches_its_slash_form_both_ways() -> None:
    assert _check("gave 1/2 tab", "Gave ½ tab.", ["gave 1/2 tab"]).status is LineStatus.SOURCE_FOUND
    assert _check("gave ½ tab", "Gave 1/2 tab.", ["gave ½ tab"]).status is LineStatus.SOURCE_FOUND


def test_a_group_is_not_matched_by_a_standalone_number() -> None:
    line = _check("BP 90/60", "BP 90 systolic.", ["BP 90/60"])
    assert _kinds(line) == [MismatchKind.VALUE]
    assert (line.number_mismatches[0].note_text) == "90/60"
    line = _check("BP 90 then 60", "BP 90/60.", ["BP 90 then 60"])
    assert _kinds(line) == [MismatchKind.VALUE]


def test_the_unit_is_read_past_the_end_of_the_quote() -> None:
    line = _check("T 37.4 F at 3am", "T 37.4 °C.", ["T 37.4"])
    [mismatch] = line.number_mismatches
    assert mismatch.kind is MismatchKind.UNIT
    assert (mismatch.draft_text, mismatch.draft_span) == ("37.4 °C", Span(start=2, end=9))
    assert (mismatch.note_text, mismatch.note_span) == ("37.4 F", Span(start=2, end=8))


def test_a_weight_unit_written_after_the_quote_is_flagged() -> None:
    units = US_LB
    line = _check("wt 80 kg today", "Weight 80 lb.", ["wt 80"], units=units)
    assert _kinds(line) == [MismatchKind.UNIT]
    assert line.number_mismatches[0].note_text == "80 kg"


def test_unit_spellings_outside_the_exact_table_are_checked() -> None:
    for drafted in ("T 37.4 \u2109", "T 37.4\u00b0 F", "T 37.4\u00a0\u00b0F", "T 37.4\u00baF"):
        line = _check("BT 37.4", drafted, ["BT 37.4"])
        assert _kinds(line) == [MismatchKind.UNIT], drafted
        assert line.number_mismatches[0].draft_text == drafted[2:]
    assert _check("BT 37.4", "T 37.4 \u2103", ["BT 37.4"]).status is LineStatus.SOURCE_FOUND


def test_a_unit_spelled_oddly_in_the_note_counts_as_written() -> None:
    line = _check("BT 37.4 \u2109", "T 37.4 °C.", ["BT 37.4"])
    assert _kinds(line) == [MismatchKind.UNIT]
    assert line.number_mismatches[0].note_text == "37.4 \u2109"


def test_a_label_glued_to_a_digit_is_not_a_label() -> None:
    line = _check("5HR 112", "HR 121.", ["5HR 112"])
    assert line.number_mismatches[0].note_text is None
    line = _check("HR_ 112", "HR 121.", ["HR_ 112"])
    assert line.number_mismatches[0].note_text is None


def test_any_occurrence_with_the_right_unit_passes() -> None:
    note = "T 37.4 F then T 37.4 C"
    assert _check(note, "T 37.4 °C.", [note]).status is LineStatus.SOURCE_FOUND


def test_a_unit_outside_every_measure_has_no_default() -> None:
    assert default_unit(Ucum.PERCENT, PH) is None


def test_a_value_glued_to_its_label_and_unit_is_still_checked() -> None:
    cases = [
        ("BT 37.4C", "BT37.9C.", PH, MismatchKind.VALUE),
        ("BT 37.4", "BT37.4F.", PH, MismatchKind.UNIT),
        ("HR 112 bpm", "HR121bpm.", PH, MismatchKind.VALUE),
        ("BP 90/60 mmHg", "BP120/80mmHg.", PH, MismatchKind.VALUE),
        ("wt 80 kg", "Wt80lb.", US_LB, MismatchKind.UNIT),
    ]
    for note, drafted, units, kind in cases:
        line = _check(note, drafted, [note], units=units)
        assert _kinds(line) == [kind], drafted
        assert line.status is LineStatus.NUMBER_MISMATCH, drafted


def test_an_edit_with_glued_values_is_checked() -> None:
    note = prepare("BT 37.4C, HR 112 bpm")
    line = _check("BT 37.4C, HR 112 bpm", "BT 37.4C, HR 112 bpm.", ["BT 37.4C, HR 112 bpm"])
    edited = recheck_line(line, "BT37.9C, HR121bpm.", note, PH)
    assert _kinds(edited) == [MismatchKind.VALUE, MismatchKind.VALUE]
    assert [m.note_text for m in edited.number_mismatches] == ["37.4", "112"]


def test_glued_note_and_spaced_line_pass_and_the_other_way_round() -> None:
    cases = [
        ("BT37.8C", "BT 37.8 °C"),
        ("T37.8C", "T 37.8C"),
        ("HR120bpm", "HR 120 bpm"),
        ("wt80kg", "Wt 80 kg"),
        ("BP90/60mmHg", "BP 90/60 mmHg"),
        ("BT 37.8 C", "BT37.8C"),
        ("HR 120 bpm", "HR120bpm"),
    ]
    for note, drafted in cases:
        line = _check(note, drafted, [note])
        assert line.status is LineStatus.SOURCE_FOUND, (note, drafted)


def test_a_quote_that_stops_inside_a_group_brings_in_the_whole_group() -> None:
    for quote in ("2 tab PO", "gave 1", "gave 1/"):
        line = _check(
            "gave 1/2 tab PO", "Gave 2 tabs PO." if quote[0] == "2" else "Gave 1 tab PO.", [quote]
        )
        assert line.source_quotes[0].span is not None, quote
        assert line.status is LineStatus.NUMBER_MISMATCH, quote
        assert _kinds(line) == [MismatchKind.VALUE], quote
    line = _check("gave 1/2 tab PO", "Gave 1 tab PO.", ["gave 1"])
    assert (line.number_mismatches[0].note_text, line.number_mismatches[0].note_span) == (
        "1/2",
        Span(start=5, end=8),
    )


def test_a_quote_that_stops_inside_a_group_still_passes_the_whole_group() -> None:
    line = _check("gave 1/2 tab PO", "Gave 1/2 tab PO.", ["2 tab PO"])
    assert line.status is LineStatus.SOURCE_FOUND


def test_a_quote_that_stops_inside_a_word_has_no_number() -> None:
    line = _check("D5LR running", "5 units insulin, D5 running.", ["D5"])
    assert line.status is LineStatus.NUMBER_MISMATCH
    assert _kinds(line)[0] is MismatchKind.VALUE


def test_a_mixed_number_is_not_matched_by_its_whole_part() -> None:
    for note in ("gave 1\u00bd tab", "gave 1 1/2 tab"):
        line = _check(note, "Gave 1 tab.", [note])
        assert _kinds(line) == [MismatchKind.VALUE], note
        assert line.number_mismatches[0].note_text is not None
    assert _check("gave 1\u00bd tab", "Gave 1 1/2 tab.", ["gave 1\u00bd tab"]).status is (
        LineStatus.SOURCE_FOUND
    )
    assert _check("gave 1\u00bd tab", "Gave 1.5 tab.", ["gave 1\u00bd tab"]).status is (
        LineStatus.NUMBER_MISMATCH
    )


def test_a_fraction_slash_group_is_not_matched_by_a_whole_number() -> None:
    line = _check("gave 1\u20442 tab", "Gave 2 tabs.", ["gave 1\u20442 tab"])
    assert _kinds(line) == [MismatchKind.VALUE]


def test_a_superscript_zero_degree_sign_is_a_unit() -> None:
    line = _check("T 37.4", "T 37.4\u2070F.", ["T 37.4"])
    assert _kinds(line) == [MismatchKind.UNIT]


def test_a_spaced_or_worded_mixed_number_is_not_matched_by_its_whole_part() -> None:
    for note in (
        "gave 1 \u00bd tab",
        "gave 1\u00a0\u00bd tab",
        "gave 1 and 1/2 tab",
        "gave 1 and \u00bd tab",
    ):
        line = _check(note, "Gave 1 tab.", [note])
        assert line.status is LineStatus.NUMBER_MISMATCH, note
        assert _kinds(line) == [MismatchKind.VALUE], note
        assert _check(note, "Gave 1\u00bd tab.", [note]).status is LineStatus.SOURCE_FOUND, note


def test_a_degree_lookalike_after_a_glued_value_is_still_checked() -> None:
    for drafted in ("T38\u00baC.", "T38\u02daC.", "T38\u2070C."):
        line = _check("T 39 C", drafted, ["T 39 C"])
        assert _kinds(line) == [MismatchKind.VALUE], drafted


def test_a_number_with_thousands_separators_is_compared_whole() -> None:
    for note, drafted in (
        ("heparin 5,000 units SC", "Heparin 5 units SC given."),
        ("IVF PNSS 1,000 mL", "IVF PNSS 1 mL"),
        ("enoxaparin 4,000 units", "enoxaparin 4 units"),
        ("heparin 5,000 units", "Heparin 5,000,000 units"),
        ("WBC 12,500", "WBC 12"),
    ):
        line = _check(note, drafted, [note])
        assert line.status is LineStatus.NUMBER_MISMATCH, (note, drafted)
        assert _kinds(line) == [MismatchKind.VALUE], (note, drafted)
    [mismatch] = _check("WBC 12,500", "WBC 12", ["WBC 12,500"]).number_mismatches
    assert (mismatch.note_text, mismatch.note_span) == ("12,500", Span(start=4, end=10))
    for drafted in ("Heparin 5000 units", "Heparin 5,000 units"):
        line = _check("heparin 5,000 units", drafted, ["heparin 5,000 units"])
        assert line.status is LineStatus.SOURCE_FOUND, drafted


def test_a_unit_spelling_the_table_does_not_read_still_counts_as_written() -> None:
    for note in ("IVF D5LR 1L", "IVF 1 L"):
        line = _check(note, "IVF 1 mL.", [note])
        assert line.status is LineStatus.NUMBER_MISMATCH, note
        assert _kinds(line) == [MismatchKind.UNIT], note
    line = _check("IVF D5LR 1L", "IVF D5LR 1 mL.", ["IVF D5LR 1L"])
    assert (line.number_mismatches[0].note_text, line.number_mismatches[0].note_span) == (
        "1L",
        Span(start=9, end=11),
    )
    assert _check("drank 600 cc", "Drank 600 mL.", ["drank 600 cc"]).status is (
        LineStatus.SOURCE_FOUND
    )
    assert _check("drank 600", "Drank 600 mL.", ["drank 600"]).status is LineStatus.SOURCE_FOUND


def test_digits_inside_a_word_must_appear_whole_in_a_quote() -> None:
    line = _check("paracetamol q4h PRN", "Paracetamol q6h PRN.", ["paracetamol q4h PRN"])
    assert line.status is LineStatus.NUMBER_MISMATCH
    [mismatch] = line.number_mismatches
    assert mismatch.kind is MismatchKind.VALUE
    assert (mismatch.draft_text, mismatch.draft_span) == ("q6h", Span(start=12, end=15))
    assert (mismatch.note_text, mismatch.note_span) == (None, None)
    line = _check("IVF D5W", "IVF D10W.", ["IVF D5W"])
    assert [m.draft_text for m in line.number_mismatches] == ["D10W"]
    line = _check("HR 121 bpm RR 20", "HR121bpmRR20.", ["HR 121 bpm RR 20"])
    assert [m.draft_text for m in line.number_mismatches] == ["HR121bpmRR20"]
    line = _check("q4h", "q4hr.", ["q4h"])
    assert [m.draft_text for m in line.number_mismatches] == ["q4hr"]
    for note, drafted in (
        ("paracetamol q4h PRN", "Paracetamol q4h PRN."),
        ("d5lr running", "D5LR running."),
    ):
        assert _check(note, drafted, [note]).status is LineStatus.SOURCE_FOUND, drafted


def test_number_words_must_appear_whole_in_a_quote() -> None:
    for drafted, word in (("Gave two tabs.", "two"), ("Gave half a tab.", "half")):
        line = _check("gave 1 tab", drafted, ["gave 1 tab"])
        assert line.status is LineStatus.NUMBER_MISMATCH, drafted
        [mismatch] = line.number_mismatches
        assert mismatch.kind is MismatchKind.VALUE
        assert (mismatch.draft_text, mismatch.draft_span) == (
            word,
            Span(start=5, end=5 + len(word)),
        )
        assert (mismatch.note_text, mismatch.note_span) == (None, None)
    line = _check("two tabs given", "Two tabs given.", ["two tabs given"])
    assert line.status is LineStatus.SOURCE_FOUND
    assert _check("seen by staff", "Seen by someone.", ["seen by staff"]).status is (
        LineStatus.SOURCE_FOUND
    )


def test_more_unit_spellings_are_checked_against_the_note() -> None:
    for drafted in ("T 37.4 degrees Fahrenheit", "T 37.4 deg F"):
        line = _check("BT 37.4", drafted, ["BT 37.4"])
        assert _kinds(line) == [MismatchKind.UNIT], drafted
        assert line.number_mismatches[0].draft_text == drafted[2:]
    assert _kinds(_check("wt 80", "Weight 80 pounds", ["wt 80"])) == [MismatchKind.UNIT]
    assert _kinds(_check("Wt 81 lbs", "Wt 81 kgs", ["Wt 81 lbs"])) == [MismatchKind.UNIT]
    assert _check("BT 37.4", "T 37.4 degrees Celsius", ["BT 37.4"]).status is (
        LineStatus.SOURCE_FOUND
    )


def test_dose_units_written_on_both_sides_must_agree() -> None:
    line = _check("cefuroxime 1 g", "Cefuroxime 1 mg given.", ["cefuroxime 1 g"])
    assert _kinds(line) == [MismatchKind.UNIT]
    [mismatch] = line.number_mismatches
    assert (mismatch.draft_text, mismatch.draft_span) == ("1 mg", Span(start=11, end=15))
    assert (mismatch.note_text, mismatch.note_span) == ("1 g", Span(start=11, end=14))
    for note, drafted in (
        ("1 g", "1 gm"),
        ("10 units", "10 U"),
        ("10 unit", "10 u"),
        ("10 IU", "10 iu"),
        ("5 mcg", "5 \u00b5g"),
        ("5 ug", "5 mcg"),
        ("2 mEq", "2 meq"),
        ("2 mmol", "2 mmol"),
        ("1 L", "1 l"),
        ("cefuroxime 1", "1 g"),
    ):
        assert _check(note, drafted, [note]).status is LineStatus.SOURCE_FOUND, (note, drafted)
    for note, drafted in (
        ("10 units", "10 mL"),
        ("10 IU", "10 units"),
        ("2 mmol", "2 mEq"),
        ("5 mcg", "5 mg"),
        ("IVF 1 mL", "IVF 1 L"),
    ):
        line = _check(note, drafted, [note])
        assert _kinds(line) == [MismatchKind.UNIT], (note, drafted)


def test_a_value_must_match_a_number_that_follows_the_same_label() -> None:
    line = _check("HR 112 RR 20", "HR 20, RR 112.", ["HR 112 RR 20"])
    assert _kinds(line) == [MismatchKind.VALUE, MismatchKind.VALUE]
    assert [(m.draft_text, m.note_text) for m in line.number_mismatches] == [
        ("20", "112"),
        ("112", "20"),
    ]
    assert line.number_mismatches[0].note_span == Span(start=3, end=6)
    ok = _check("HR 112 RR 20", "HR 112, RR 20.", ["HR 112 RR 20"])
    assert ok.status is LineStatus.SOURCE_FOUND
    unlabelled = _check("HR 112 RR 20", "Pulse 112, breathing 20.", ["HR 112 RR 20"])
    assert unlabelled.status is LineStatus.SOURCE_FOUND


def test_more_spacings_and_an_ampersand_make_a_mixed_number_in_the_note() -> None:
    for note in (
        "GAVE 1 AND 1/2 TAB",
        "gave 1 & 1/2 tab",
        "gave 1  \u00bd tab",
        "gave 1\t\u00bd tab",
        "gave 1 and\u00a01/2 tab",
    ):
        line = _check(note, "Gave 1 tab.", [note])
        assert line.status is LineStatus.NUMBER_MISMATCH, note
        assert _kinds(line) == [MismatchKind.VALUE], note


@st.composite
def _notes_and_lines(draw: st.DrawFn) -> tuple[str, str, list[str], bool]:
    note = draw(st.text())
    start = draw(st.integers(min_value=0, max_value=len(note)))
    end = draw(st.integers(min_value=start, max_value=len(note)))
    piece = st.one_of(st.just(note[start:end]), st.text())
    return note, draw(piece), draw(st.lists(piece, max_size=3)), draw(st.booleans())


@given(_notes_and_lines())
def test_checking_a_line_never_raises_on_arbitrary_text(
    case: tuple[str, str, list[str], bool],
) -> None:
    note, text, quotes, own = case
    for units in (PH, US_LB):
        line = _check(note, text, quotes, own=own, units=units)
        assert line.text == text
        assert recheck_line(line, text, prepare(note), units).text == text


def _rate_status(note: str, text: str) -> DraftLine:
    return _check(note, text, [note])


def test_a_different_rate_unit_is_a_unit_mismatch_over_the_whole_rate() -> None:
    line = _rate_status("heparin 1000 units/hr", "Heparin 1000 mL/hr.")
    assert line.status is LineStatus.NUMBER_MISMATCH
    [mismatch] = line.number_mismatches
    assert mismatch.kind is MismatchKind.UNIT
    assert (mismatch.draft_text, mismatch.note_text) == ("1000 mL/hr", "1000 units/hr")
    assert mismatch.draft_span == Span(start=8, end=18)
    assert mismatch.note_span == Span(start=8, end=21)


def test_rate_units_that_differ_are_flagged() -> None:
    for note, text, on in [
        ("dopamine 5 mcg/kg/min", "Dopamine 5 mg/kg/min.", "5 mg/kg/min"),
        ("dopamine 5 mcg/kg/min", "Dopamine 5 mcg/min.", "5 mcg/min"),
        ("heparin 1000 units/hr", "Heparin bolus 1000 units.", "1000 units"),
        ("heparin 1000 u/h", "Heparin 1000 mL/h.", "1000 mL/h"),
        ("30gtts/min", "30 gtts/hr.", "30 gtts/hr"),
    ]:
        line = _rate_status(note, text)
        assert line.status is LineStatus.NUMBER_MISMATCH, (note, text)
        [mismatch] = line.number_mismatches
        assert mismatch.kind is MismatchKind.UNIT
        assert mismatch.draft_text == on


def test_a_volume_over_hours_is_checked_against_its_written_unit() -> None:
    line = _rate_status("D5LR 1L/8hrs", "D5LR 1 mL over 8 hrs.")
    assert line.status is LineStatus.NUMBER_MISMATCH
    [mismatch] = line.number_mismatches
    assert (mismatch.kind, mismatch.draft_text) == (MismatchKind.UNIT, "1 mL")
    assert _rate_status("D5LR 1L/8hrs", "D5LR 1 L over 8 hrs.").status is LineStatus.SOURCE_FOUND


def test_the_same_rate_in_another_spelling_agrees() -> None:
    for text in ["Heparin 1000 units/h.", "Heparin 1000 units/hr.", "Heparin 1000 U/hours."]:
        assert _rate_status("heparin 1000 units/hr", text).status is LineStatus.SOURCE_FOUND


def _flagged_unit(note: str, text: str) -> None:
    line = _rate_status(note, text)
    assert line.status is LineStatus.NUMBER_MISMATCH, (note, text)
    assert {m.kind for m in line.number_mismatches} == {MismatchKind.UNIT}, (note, text)


def test_spaced_and_worded_rates_are_compared_too() -> None:
    for note, text in [
        ("dopamine 5 mcg / kg / min", "Dopamine 5 mcg / kg / hr."),
        ("dopamine 5 mcg/ kg/ min", "Dopamine 5 mcg/ min."),
        ("heparin 1000 units / hr", "Heparin bolus 1000 units."),
        ("heparin 1000 units /hr", "Heparin bolus 1000 units."),
        ("heparin 1000 units per hr", "Heparin 1000 units per min."),
        ("heparin 1000 units per hour", "Heparin bolus 1000 units."),
    ]:
        _flagged_unit(note, text)


def test_a_worded_rate_equals_the_same_rate_with_slashes() -> None:
    for note, text in [
        ("heparin 1000 units per hour", "Heparin 1000 units/hr."),
        ("dopamine 5 mcg per kg per min", "Dopamine 5 mcg/kg/min."),
        ("dopamine 5 mcg/kg per MIN", "Dopamine 5 mcg / kg / min."),
        ("D5LR 1 L / 8 hrs", "D5LR 1 L over 8 hrs."),
        ("oxycodone 5 mg per NGT", "Oxycodone 5 mg via NGT."),
    ]:
        assert _rate_status(note, text).status is LineStatus.SOURCE_FOUND, (note, text)


def test_only_dose_and_volume_units_take_a_rate() -> None:
    for note, text in [
        ("T 37.8C/HR 110/RR 22", "Temperature 37.8 °C."),
        ("BP 120/80 mmHg/HR 80", "BP 120/80 mmHg."),
    ]:
        assert _rate_status(note, text).status is LineStatus.SOURCE_FOUND, (note, text)


def test_drops_are_compared_and_gtt_equals_gtts() -> None:
    _flagged_unit("IVF 30 mL/hr", "IVF 30 gtts/hr.")
    _flagged_unit("30gtts/min", "30 gtt/hr.")
    assert _rate_status("30gtts/min", "30 gtt/min.").status is LineStatus.SOURCE_FOUND


def test_a_rate_on_the_line_needs_a_rate_in_the_note() -> None:
    line = _check("heparin 1000 at noon", "Heparin 1000 mL/hr.", ["heparin 1000"])
    assert line.status is LineStatus.NUMBER_MISMATCH
    _flagged_unit("heparin 1000", "Heparin 1000 units/hr.")
    assert _rate_status("heparin 1000", "Heparin 1000 units.").status is LineStatus.SOURCE_FOUND


def test_a_bare_rate_after_the_note_number_is_the_rate_the_line_may_write() -> None:
    assert _rate_status("IVF 100/hr", "IVF 100 mL/hr.").status is LineStatus.SOURCE_FOUND
    assert _rate_status("IVF 100 per hour", "IVF 100 mL/hr.").status is LineStatus.SOURCE_FOUND
    _flagged_unit("IVF 100/hr", "IVF 100 mL/min.")


def test_a_same_valued_note_number_without_a_unit_does_not_excuse_a_wrong_unit() -> None:
    for note, text, on in [
        ("SpO2 95% 2L NC", "On 2 mL NC.", "2 mL"),
        ("on O2 2 LPM via NC, SpO2 95%", "On O2 at 2 mL/min via NC.", "2 mL/min"),
        (
            "at 1000 started heparin 1000 units/hr",
            "Heparin bolus 1000 units given at 1000.",
            "1000 units",
        ),
    ]:
        line = _rate_status(note, text)
        assert line.status is LineStatus.NUMBER_MISMATCH, (note, text)
        [mismatch] = line.number_mismatches
        assert (mismatch.kind, mismatch.draft_text) == (MismatchKind.UNIT, on), (note, text)


def test_oxygen_in_litres_per_minute_is_checked_against_the_note() -> None:
    _flagged_unit("oxygen 2 L/m", "Oxygen at 2 mL/min.")
    for note, text in [
        ("SpO2 95% 2L NC", "On 2 L NC."),
        ("SpO2 95% 2L NC", "SpO2 95%, on 2 L NC."),
        ("on O2 2 lpm via NC, SpO2 95%", "On O2 at 2 L/min via NC."),
        ("on O2 2 LPM", "On O2 at 2 lpm."),
        ("O2 2 L/min", "On O2 at 2 lpm."),
        ("O2 2 lpm", "On O2 2 L/min."),
    ]:
        assert _rate_status(note, text).status is LineStatus.SOURCE_FOUND, (note, text)
    _flagged_unit("O2 2 lpm", "On O2 2 mL/min.")


def test_a_weight_value_shared_with_a_dose_flags_in_a_pound_facility() -> None:
    line = _check(
        "wt 80, furosemide 80 mg IV", "Weight 80 lb.", ["wt 80, furosemide 80 mg IV"], units=US_LB
    )
    assert line.status is LineStatus.NUMBER_MISMATCH


def test_per_kilogram_is_a_rate_in_either_spelling() -> None:
    _flagged_unit("dopamine 5 mcg per kilogram per minute", "Dopamine 5 mcg.")
    assert (
        _rate_status("dopamine 5 mcg/kilogram/min", "Dopamine 5 mcg/kg/min.").status
        is LineStatus.SOURCE_FOUND
    )


def test_dose_units_spelled_as_words_are_compared() -> None:
    _flagged_unit("norepi 0.05 micrograms/kg/min", "Norepinephrine 0.05 mg/kg/min.")
    _flagged_unit("1 mg", "1 gram given.")
    for note, text in [
        ("100 mL", "100 milliliters given."),
        ("100 milliliters", "100 mL given."),
        ("100 millilitres", "100 cc given."),
        ("500 milligrams", "500 mg given."),
        ("500 mg", "500 milligrams given."),
        ("2 litres", "2 L given."),
        ("1 gram", "1 g given."),
        ("5 micrograms", "5 mcg given."),
    ]:
        assert _rate_status(note, text).status is LineStatus.SOURCE_FOUND, (note, text)


def test_a_word_after_a_slash_that_is_not_a_denominator_is_not_a_rate() -> None:
    for note, text in [
        ("paracetamol 500mg/tab", "Paracetamol 500 mg given."),
        ("2 mg/dose", "2 mg."),
        ("30 mg / IV", "30 mg IV."),
    ]:
        assert _rate_status(note, text).status is LineStatus.SOURCE_FOUND, (note, text)


def test_a_slash_before_a_heart_rate_makes_the_rate_unsure_so_both_readings_flag() -> None:
    for note in [
        "insulin 5 units / HR 88",
        "insulin 5 units/HR 88",
        "insulin 5 units/hr 88",
        "insulin 5 units / HR 88, RR 18",
        "insulin 5 units / HR 88.",
        "insulin 5 units / HR 88 bpm",
        "insulin 5 units / HR 88 given",
        "insulin 5 units / HR 102",
        "insulin 5 units / HR: 88",
        "insulin 5 units / HR:88",
        "insulin 5 units / HR=88",
        "insulin 5 units / HR - 88",
        "insulin 5 units / HR of 88",
        "insulin 5 units / HR 88bpm",
        "insulin 5 units / HR 88 BPM",
        "insulin 5 units / HR 88BPM",
        "insulin 5 units / HR OF 88",
        "insulin 5 units / HR Of 88",
        "insulin 5 units / HR 88Bpm",
        "INSULIN 5 UNITS / HR OF 88",
        "insulin 5 units / HR \u2013 88",
        "insulin 5 units / HR \u2014 88",
        "insulin 5 units / HR\u201488",
        "insulin 5 units / HR 88/min",
        "insulin 5 units / HR 88/MIN",
        "insulin 5 units/hr 88/min",
        "insulin 5 units / HR 88/minute",
        "insulin 5 units / HR 88/MINUTE",
        "insulin 5 units / HR 88/mins",
        "insulin 5 units / HR 88/Mins",
        "insulin 5 units / HR 88/minutes",
        "insulin 5 units / HR 88/ min",
        # A single letter or "drop" after the number is a word, not a unit.
        "insulin 5 units / HR 88 L radial",
        "insulin 5 units / HR 88 L arm",
        "insulin 5 units / HR 88 l radial",
        "insulin 5 units / HR: 88 L radial",
        "insulin 5 units / HR 88 L.",
        "insulin 5 units / HR 88 L) radial",
        "insulin 5 units / HR 88 drops to 60",
        "insulin 5 units / HR 120 drop to 90",
        "insulin 5 units / HR 88 u/a",
        "insulin 5 units / HR 88 U/A sent",
        "insulin 5 units / HR 88 U waves",
        "insulin 5 units / HR 88 g",
        "insulin 5 units / HR 88 G",
        "insulin 5 units / HR 88 g.",
        # "CC:" is a chief complaint, not cubic centimetres.
        "insulin 5 units / HR 88 CC: chest pain",
        "insulin 5 units / HR 88 CC : chest pain",
        # Words that start like a unit or a vital sign.
        "insulin 5 units / HR 88 CCU",
        "insulin 5 units / HR 88 mgmt per MD",
        "insulin 5 units / HR 88 good volume",
        "insulin 5 units / HR 88 un-labored",
        "insulin 5 units / HR 88 unlabored",
        "insulin 5 units / HR 88 irregular",
        "insulin 5 units / HR 88 lying",
        "insulin 5 units / HR 88 Lt radial",
        "insulin 5 units / HR 88 R radial",
        "insulin 5 units / HR 120 dropped to 90",
        "insulin 5 units / HR 88 BP 120/80",
        "insulin 5 units / HR 88 RR 18",
        "insulin 5 units / HR 88 T 37",
        "insulin 5 units / HR 88 GCS 15",
        "insulin 5 units / HR 88 mmHg",
        "insulin 5 units / HR 88 sinus",
        "insulin 5 units / HR 88 NSR",
        "insulin 5 units / HR 88 SR",
        "insulin 5 units / HR 88 AF",
        "insulin 5 units / HR 88 A-fib",
    ]:
        _flagged_unit(note, "Insulin 5 units/hr.")
        _flagged_unit(note, "Insulin 5 units.")
    line = _rate_status("insulin 5 units / HR 88", "Insulin 5 units.")
    assert [m.note_text for m in line.number_mismatches] == ["5 units / HR"]
    _flagged_unit("heparin 1000 units, HR 88", "Heparin 1000 units/hr 88.")
    _flagged_unit("IVF 100/hr 88", "IVF 100 mL.")
    assert _rate_status("insulin 5 units, HR 88", "Insulin 5 units.").status is (
        LineStatus.SOURCE_FOUND
    )


def test_a_rate_followed_by_a_time_volume_weight_or_other_number_is_still_a_rate() -> None:
    for note, text in [
        ("heparin 1000 units/hr 10am", "Heparin 1000 units."),
        ("heparin 1000 units/hr 10 am", "Heparin 1000 units."),
        ("heparin 1000 units/hr \t10am", "Heparin 1000 units."),
        ("heparin 1000 units/hr 1000", "Heparin 1000 units."),
        ("insulin 5 units/hr 0800", "Insulin 5 units."),
        ("insulin 5 units / hr 0800", "Insulin 5 units."),
        ("insulin 5 units/HR 0800", "Insulin 5 units."),
        ("IVF 100 mL/hr 2L total", "IVF 100 mL."),
        ("IVF 100 mL/hr 2 L total", "IVF 100 mL."),
        ("IVF 100 cc/hr 1L", "IVF 100 mL."),
        ("NS 100 mL/hr 8 hrs", "NS 100 mL."),
        ("IVF 100/hr 0800", "IVF 100 mL."),
        ("dopamine 5 mcg/kg/hr 70kg", "Dopamine 5 mcg/kg."),
        ("heparin 18 units/kg/hr 1300", "Heparin 18 units/kg."),
        ("drip 5 mg/hr 0800", "Drip 5 mg."),
        ("drip 5 mg/kg/hr 0800", "Drip 5 mg/kg."),
        ("insulin 5 units/hour 2", "Insulin 5 units."),
        ("insulin 5 units/hrs 2", "Insulin 5 units."),
        ("insulin 5 units/h 88", "Insulin 5 units."),
        ("insulin 5 units / hour 88", "Insulin 5 units."),
        ("insulin 5 units/hr 1:30", "Insulin 5 units."),
        ("insulin 5 units/hr 10:30", "Insulin 5 units."),
        ("insulin 5 units/hr of 5", "Insulin 5 units."),
        ("heparin 1000 units/hr 25000 units in 250 mL", "Heparin 1000 units."),
        ("insulin 5 units/hr 88mL", "Insulin 5 units."),
        ("insulin 5 units/hr 88.5", "Insulin 5 units."),
        ("insulin 5 units/hr\n88", "Insulin 5 units."),
        ("heparin 1000 units 10am", "Heparin 1000 units/hr 10am."),
    ]:
        _flagged_unit(note, text)
    for note in ["insulin 5 units/hr 0800", "insulin 5 units/hr 10:30"]:
        assert _rate_status(note, "Insulin 5 units/hr.").status is LineStatus.SOURCE_FOUND, note


def test_a_dose_volume_or_weight_after_the_number_means_it_is_not_a_heart_rate() -> None:
    for note, faithful, dropped in [
        ("heparin 1000 units/hr = 10 mL/hr", "Heparin 1000 units/hr.", "Heparin 1000 units."),
        ("heparin 1000 units/hr: 25 mL/hr", "Heparin 1000 units/hr.", "Heparin 1000 units."),
        ("insulin 5 units/hr - 10 units given", "Insulin 5 units/hr.", "Insulin 5 units."),
        ("IVF 100 mL/hr of 50 mL", "IVF 100 mL/hr.", "IVF 100 mL."),
        ("IVF 100 mL/hr - 500 mL bag", "IVF 100 mL/hr.", "IVF 100 mL."),
        ("IVF 100 mL/hr=50 cc", "IVF 100 mL/hr.", "IVF 100 mL."),
        ("dopamine 5 mcg/kg/hr - 70 kg", "Dopamine 5 mcg/kg/hr.", "Dopamine 5 mcg/kg."),
        (
            "heparin 1000 units/hr 25000 units in 250 mL",
            "Heparin 1000 units/hr.",
            "Heparin 1000 units.",
        ),
    ]:
        assert _rate_status(note, faithful).status is LineStatus.SOURCE_FOUND, (note, faithful)
        _flagged_unit(note, dropped)


def test_units_per_litre_per_with_a_line_break_and_naming_without_a_rate() -> None:
    _flagged_unit("ALT 40 U/L", "ALT 40 units.")
    _flagged_unit("heparin 5 mg\nper hr", "Heparin 5 mg.")
    line = _rate_status("IVF 100/hr, NS 100 mL bolus", "Infusing at 100 kg.")
    assert line.status is LineStatus.NUMBER_MISMATCH
    assert [m.note_text for m in line.number_mismatches] == ["100 mL"]


def test_a_spaced_rate_with_no_number_after_the_denominator_is_still_a_rate() -> None:
    for note, text in [
        ("heparin 5 units / hr", "Heparin 5 units."),
        ("heparin 5 units / hr x 2", "Heparin 5 units."),
        ("heparin 5 units / hr then stop", "Heparin 5 units."),
    ]:
        _flagged_unit(note, text)
    assert _rate_status("heparin 5 units / hr", "Heparin 5 units/hr.").status is (
        LineStatus.SOURCE_FOUND
    )


def test_a_line_break_inside_a_rate_is_read_like_a_space() -> None:
    for note, text in [
        ("heparin 5 mg/\nhr", "Heparin 5 mg."),
        ("heparin 5 mg\n/hr", "Heparin 5 mg."),
        ("heparin 5 mg per\nhr", "Heparin 5 mg."),
        ("heparin 5 mg/\r\nhr", "Heparin 5 mg/min."),
        ("heparin 5 mg/hr", "Heparin 5 mg/\nmin."),
        ("heparin 5 mg/hr", "Heparin 5 mg."),
        ("IVF 100/\nhr", "IVF 100 mL."),
    ]:
        _flagged_unit(note, text)
    for note, text in [
        ("heparin 5 mg/\nhr", "Heparin 5 mg/hr."),
        ("heparin 5 mg/hr", "Heparin 5 mg per\nhour."),
    ]:
        assert _rate_status(note, text).status is LineStatus.SOURCE_FOUND, (note, text)


def test_a_concentration_unit_must_match_whole() -> None:
    for note, text in [
        ("Hgb 12 g/dL", "Hgb 12 g/L."),
        ("Hgb 12 g/L", "Hgb 12 g/dL."),
        ("Hgb 12 g/dL", "Hgb 12 mg/dL."),
        ("Glucose 12 mg/dL", "Glucose 12 g/dL."),
        ("Glucose 12 mg/dL", "Glucose 12 mg."),
        ("Glucose 12 mg/dL", "Glucose 12 mg/hr."),
        ("Glucose 12 mg", "Glucose 12 mg/dL."),
        ("Glucose 12 mg/hr", "Glucose 12 mg/dL."),
        ("Hgb 12 g", "Hgb 12 g/L."),
        ("Hgb 12 g/L", "Hgb 12 g."),
        ("K 4 mmol/L", "K 4 mEq/L."),
        ("K 4 mEq/L", "K 4 mmol/L."),
        ("K 4 mmol/L", "K 4 mmol."),
        ("Hgb 12 g/dL", "Hgb 12 g."),
    ]:
        _flagged_unit(note, text)
    for note, text in [
        ("Hgb 12 g/dL", "Hgb 12 g/dL."),
        ("Hgb 12 g/dL", "Hgb 12 g / dL."),
        ("Hgb 12 g/L", "Hgb 12 g/L."),
        ("Hgb 12 g/L", "Hgb 12 g / L."),
        ("Hgb 12 gm/L", "Hgb 12 g/L."),
        ("Glucose 12 mg/dl", "Glucose 12 mg/dL."),
        ("K 4 mEq/L", "K 4 meq/l."),
        ("K 4 mmol/L", "K 4 mmol/L."),
    ]:
        assert _rate_status(note, text).status is LineStatus.SOURCE_FOUND, (note, text)


def test_one_letter_shorthand_with_a_slash_is_still_not_a_unit() -> None:
    for note, text in [
        ("pt c/o pain 5", "Pain 5."),
        ("f/u 3 days", "Follow up 3 days."),
        ("u/a 2 done", "Urinalysis 2 done."),
    ]:
        assert _rate_status(note, text).status is LineStatus.SOURCE_FOUND, (note, text)


def test_the_mismatch_names_the_note_number_that_carries_the_rate() -> None:
    line = _rate_status("IVF 100/hr, NS 100 mL bolus", "Infusing at 100 mL/min.")
    [mismatch] = line.number_mismatches
    assert mismatch.note_text == "100/hr"
    line = _rate_status("IVF 100 mL/hr, NS 100 mL bolus", "Infusing at 100 mL/min.")
    [mismatch] = line.number_mismatches
    assert mismatch.note_text == "100 mL/hr"


def test_litres_are_a_volume_unit_for_the_facility_default() -> None:
    for text in ["IVF 100 L.", "IVF 100 l.", "IVF 100 litres.", "IVF 100 liters.", "IVF 100L."]:
        _flagged_unit("IVF 100", text)
    for note, text in [
        ("IVF 100", "IVF 100 mL."),
        ("IVF 1 L", "IVF 1 liter."),
        ("IVF 1L", "IVF 1 L."),
    ]:
        assert _rate_status(note, text).status is LineStatus.SOURCE_FOUND, (note, text)
    _flagged_unit("IVF 1 L", "IVF 1 mL.")
    _flagged_unit("IVF 100 mL", "IVF 100 L.")


def test_a_rate_the_note_writes_after_a_bare_number_is_required_in_the_line() -> None:
    for note, text in [
        ("heparin 1000/hr", "Heparin bolus 1000 units."),
        ("heparin 1000 / hr", "Heparin bolus 1000 units."),
        ("heparin 1000 per hour", "Heparin bolus 1000 units."),
        ("IVF 100/hr", "IVF 100 mL."),
        ("heparin 1000/hr", "Heparin 1000 units/min."),
    ]:
        _flagged_unit(note, text)
    for note, text in [
        ("heparin 1000/hr", "Heparin 1000 units/hr."),
        ("IVF 100/hr", "IVF 100 mL/hr."),
        ("HR 88/min", "HR 88 bpm."),
        ("RR 18/min", "RR 18."),
    ]:
        assert _rate_status(note, text).status is LineStatus.SOURCE_FOUND, (note, text)


def test_per_week_per_month_and_per_shift_are_rates_compared_by_meaning() -> None:
    for note, text in [
        ("MTX 15 mg/week", "MTX 15 mg/month."),
        ("MTX 15 mg/week", "MTX 15 mg/day."),
        ("MTX 15 mg/wk", "MTX 15 mg/mo."),
        ("MTX 15 mg per month", "MTX 15 mg per week."),
        ("MTX 15 mg/week", "MTX 15 mg."),
        ("MTX 15 mg", "MTX 15 mg/week."),
        ("15 mg/shift", "15 mg/day."),
        ("15 mg/day", "15 mg per shift."),
        ("15 mg/shift", "15 mg/hr."),
    ]:
        _flagged_unit(note, text)
    for note, text in [
        ("MTX 15 mg/week", "MTX 15 mg per week."),
        ("MTX 15 mg/wk", "MTX 15 mg/weeks."),
        ("MTX 15 mg/month", "MTX 15 mg/mo."),
        ("15 mg/shift", "15 mg per shifts."),
    ]:
        assert _rate_status(note, text).status is LineStatus.SOURCE_FOUND, (note, text)


def test_a_spelled_out_rate_is_read_whole() -> None:
    for note, text in [
        ("5 mcg per kilograms per minute", "5 mcg/kg."),
        ("5 mcg per kilograms per minute", "5 mcg/kg/hr."),
        ("5 micrograms per kilograms per minutes", "5 mcg/kg."),
        ("dopamine 5 mcg/kg/min", "Dopamine 5 micrograms per kilograms per hour."),
        ("5 mcg per kilograms per minute", "5 mcg."),
    ]:
        _flagged_unit(note, text)
    for note, text in [
        ("5 mcg per kilograms per minute", "5 mcg/kg/min."),
        ("5 mcg/kg/min", "5 micrograms per kilograms per minute."),
    ]:
        assert _rate_status(note, text).status is LineStatus.SOURCE_FOUND, (note, text)


def test_a_different_rate_written_straight_after_the_lines_number_is_flagged() -> None:
    for note, text in [
        ("heparin 1000/hr", "Heparin 1000/min."),
        ("heparin 1000/hr", "Heparin 1000 per minute."),
        ("IVF 100/hr", "IVF 100/min."),
        ("heparin 1000 units/hr", "Heparin 1000/min."),
    ]:
        _flagged_unit(note, text)


def test_a_rate_after_the_lines_number_is_clean_where_the_note_has_none_or_agrees() -> None:
    for note, text in [
        ("HR 88 bpm", "HR 88/min."),
        ("HR 88/min", "HR 88 bpm."),
        ("RR 18/min", "RR 18."),
        ("heparin 1000/hr", "Heparin 1000/hr."),
        ("heparin 1000/hr", "Heparin 1000 per hour."),
        ("heparin 1000 units/hr", "Heparin 1000/hr."),
        ("heparin 1000", "Heparin 1000/hr."),
    ]:
        assert _rate_status(note, text).status is LineStatus.SOURCE_FOUND, (note, text)


def test_a_rate_the_note_writes_elsewhere_for_the_same_value_does_not_excuse_a_dropped_rate() -> (
    None
):
    for note, text in [
        ("IVF 100/hr. Urine 100", "Infusing at 100/min."),
        ("IVF 100/hr. Urine 100", "Running 100/min."),
        ("IVF 100/hr. Urine 100", "100/min."),
        ("heparin 1000/hr, bolus 1000", "Drip 1000/min."),
        ("heparin 1000 units/hr, 1000 units bolus given", "Drip at 1000/min."),
        ("IVF 100 mL/hr, NS 100 mL bolus", "Infusing at 100/min."),
        ("IVF 100/hr, NS 100 mL bolus", "Infusing at 100/min."),
        ("IVF 100/hr. Urine 100", "Infusing at 100 mL."),
        ("heparin 1000/hr, bolus 1000", "Drip at 1000 units."),
    ]:
        _flagged_unit(note, text)
    line = _rate_status("IVF 100/hr, NS 100 mL bolus", "Infusing at 100/min.")
    assert [m.note_text for m in line.number_mismatches] == ["100/hr"]
    line = _rate_status("heparin 1000/hr, bolus 1000", "Drip at 1000 units.")
    assert [m.note_text for m in line.number_mismatches] == ["1000/hr"]


def test_the_rate_check_stays_clean_for_vitals_and_agreeing_rates() -> None:
    for note, text in [
        ("HR 88 bpm", "HR 88/min."),
        ("HR 88/min", "HR 88 bpm."),
        ("RR 18/min", "RR 18."),
        ("heparin 1000", "Heparin 1000/hr."),
        ("IVF 100/hr then 100/min", "Running 100/min."),
        ("O2 2 lpm", "O2 2/min."),
        ("dopamine 5 mcg/kg/min", "Dopamine 5/kg/min."),
    ]:
        assert _rate_status(note, text).status is LineStatus.SOURCE_FOUND, (note, text)
    only_urine = _check("IVF 100/hr. Urine 100", "Urine 100.", ["Urine 100"])
    assert only_urine.status is LineStatus.SOURCE_FOUND
    only_urine = _check("IVF 100/hr. Urine 100", "Urine 100 mL.", ["Urine 100"])
    assert only_urine.status is LineStatus.SOURCE_FOUND
