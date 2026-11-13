"""The three synthetic demo cases: the acceptance test, the API seed and the mock data."""

import re
import unicodedata

from nursing_core.demo import DEMO_FACILITIES, DEMO_PERSONAS, DemoCase, load_demo_cases
from nursing_core.domain.facility import FacilityProfile
from nursing_core.domain.notes import LineReview, LineStatus, MismatchKind
from nursing_core.domain.shifts import shift_containing
from nursing_core.domain.users import Role

_CURLY = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"'})


def normalise(text: str) -> str:
    """The comparison the quote check uses: NFKC, casefold, straight quotes, one space."""
    folded = unicodedata.normalize("NFKC", text).casefold().translate(_CURLY)
    return re.sub(r"\s+", " ", folded).strip()


def facility_of(case: DemoCase) -> FacilityProfile:
    return next(f for f in DEMO_FACILITIES if f.key == case.facility_key)


def test_every_case_validates() -> None:
    cases = load_demo_cases()
    assert [case.key for case in cases] == ["demo-1", "demo-2", "demo-3"]
    assert all(case.synthetic for case in cases)


def test_spans_point_at_their_quotes() -> None:
    for case in load_demo_cases():
        note = case.rough_note.text
        for line in case.expected_draft.lines():
            for quote in line.source_quotes:
                assert quote.span is not None, (case.key, line.id)
                found = note[quote.span.start : quote.span.end]
                assert normalise(found) == normalise(quote.text), (case.key, line.id)


def test_mismatch_spans_point_at_their_numbers() -> None:
    for case in load_demo_cases():
        for line in case.expected_draft.lines():
            for mismatch in line.number_mismatches:
                draft = line.text[mismatch.draft_span.start : mismatch.draft_span.end]
                assert draft == mismatch.draft_text, (case.key, line.id)
                assert mismatch.note_span is not None
                note = case.rough_note.text[mismatch.note_span.start : mismatch.note_span.end]
                assert note == mismatch.note_text, (case.key, line.id)


def test_checklist_spans_point_into_the_note() -> None:
    for case in load_demo_cases():
        for item in case.expected_checklist:
            if item.note_span is not None:
                assert not item.missing
                assert case.rough_note.text[item.note_span.start : item.note_span.end].strip()


def test_cases_cover_all_four_statuses_and_both_mismatch_kinds() -> None:
    lines = [line for case in load_demo_cases() for line in case.expected_draft.lines()]
    assert {line.status for line in lines} == set(LineStatus)
    kinds = {m.kind for line in lines for m in line.number_mismatches}
    assert kinds == set(MismatchKind)


def test_expected_drafts_are_fresh_from_the_model() -> None:
    for case in load_demo_cases():
        model_lines = sum(
            1 + len(e.data) + len(e.action) + len(e.response) for e in case.model_output.entries
        )
        lines = list(case.expected_draft.lines())
        assert len(lines) == model_lines
        assert all(line.review is LineReview.PENDING for line in lines)
        assert all(line.text == line.ai_text for line in lines)


def test_one_case_has_two_foci_and_an_empty_response() -> None:
    drafts = {case.key: case.expected_draft for case in load_demo_cases()}
    assert len(drafts["demo-2"].entries) == 2
    assert any(not entry.response for entry in drafts["demo-2"].entries)


def test_no_case_flags_code_status() -> None:
    cases = load_demo_cases()
    assert any(case.context.code_status == "DNR" for case in cases)
    for case in cases:
        assert all("code" not in item.subject.casefold() for item in case.expected_checklist)


def test_each_case_shift_matches_its_facility() -> None:
    for case in load_demo_cases():
        note = case.rough_note
        assert note.shift == shift_containing(note.written_at, facility_of(case))


def test_demo_display_names_are_demo_patient() -> None:
    names = [case.display_name for case in load_demo_cases()]
    assert names == ["Demo patient A", "Demo patient B", "Demo patient C"]


def test_model_outputs_never_hold_a_known_name() -> None:
    for case in load_demo_cases():
        identity = case.patient
        names = [identity.given_name, identity.family_name, *identity.nicknames]
        names += [part for relative in identity.relatives for part in relative.name.split()]
        output = case.model_output.model_dump_json().casefold()
        assert not [name for name in names if name.casefold() in output], case.key


def test_demo_facilities_and_personas() -> None:
    assert [f.key for f in DEMO_FACILITIES] == ["ph-demo", "us-demo"]
    assert all("SYNTHETIC" in f.name for f in DEMO_FACILITIES)
    assert len({p.id for p in DEMO_PERSONAS}) == len(DEMO_PERSONAS)
    admins = [p for p in DEMO_PERSONAS if p.role is Role.ADMIN]
    assert len(admins) == 1
    assert admins[0].facility_key is None
    for key in ("ph-demo", "us-demo"):
        roles = sorted(p.role for p in DEMO_PERSONAS if p.facility_key == key)
        assert roles == [Role.HEAD_NURSE, Role.STAFF_NURSE]


def test_each_case_is_written_by_a_staff_nurse_of_its_facility() -> None:
    for case in load_demo_cases():
        author = next(p for p in DEMO_PERSONAS if p.id == case.rough_note.author_id)
        assert author.role is Role.STAFF_NURSE
        assert author.facility_key == case.facility_key
