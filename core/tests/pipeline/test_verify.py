"""Deciding each line's status from its quotes, numbers and units."""

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
    [mismatch] = line.number_mismatches
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
