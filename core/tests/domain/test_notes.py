"""Note, draft, checklist, job and patient types: the shapes every lane builds against."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from nursing_core.domain.errors import ReviewIncomplete
from nursing_core.domain.facility import Locale, NoteFormat, preset
from nursing_core.domain.jobs import DraftJob, JobFailure, JobStatus
from nursing_core.domain.model_output import DraftRequest, ModelFdarDraft
from nursing_core.domain.notes import (
    ChecklistItem,
    ChecklistRule,
    Discard,
    DraftLine,
    FdarDraft,
    FdarEntry,
    FdarSection,
    GenerationInfo,
    LineReview,
    LineStatus,
    Note,
    NoteStatus,
    RoughNote,
    Signature,
    SourceQuote,
    Span,
    needs_review,
    unresolved_line_ids,
)
from nursing_core.domain.patient import PatientContext, PatientIdentity, Relative
from nursing_core.domain.shifts import shift_containing
from nursing_core.domain.users import Role, can_edit_settings, can_see_facility, can_write_notes
from pydantic import ValidationError

PH = preset("PH", "ph-demo", "SYNTHETIC Demo Hospital (PH)")
WRITTEN = datetime(2026, 11, 12, 5, 10, tzinfo=ZoneInfo("Asia/Manila"))


def line(
    line_id: str,
    section: FdarSection = FdarSection.DATA,
    status: LineStatus = LineStatus.SOURCE_FOUND,
    review: LineReview = LineReview.PENDING,
) -> DraftLine:
    return DraftLine(
        id=line_id,
        section=section,
        text="Still weak.",
        ai_text="Still weak.",
        status=status,
        review=review,
        source_quotes=[SourceQuote(text="still weak", span=Span(start=0, end=10))],
        number_mismatches=[],
    )


def entry(prefix: str, *data: DraftLine) -> FdarEntry:
    return FdarEntry(
        focus=line(f"{prefix}-F", FdarSection.FOCUS, LineStatus.SUMMARY),
        data=list(data),
        action=[],
        response=[],
    )


def rough_note(text: str = "pt still weak") -> RoughNote:
    return RoughNote(
        id=uuid4(),
        encounter_id=uuid4(),
        author_id=uuid4(),
        text=text,
        written_at=WRITTEN,
        shift=shift_containing(WRITTEN, PH),
        note_format=NoteFormat.FDAR,
    )


def generation() -> GenerationInfo:
    return GenerationInfo(
        provider="fake",
        model="fake",
        prompt_version="fdar-v1",
        input_tokens=0,
        output_tokens=0,
        cost_usd=Decimal(0),
        latency_ms=0,
    )


def test_span_must_be_non_empty_and_ordered() -> None:
    assert Span(start=0, end=1).end == 1
    for start, end in ((3, 3), (4, 3), (-1, 2)):
        with pytest.raises(ValidationError):
            Span(start=start, end=end)


@pytest.mark.parametrize("status", list(LineStatus))
@pytest.mark.parametrize("review", list(LineReview))
def test_needs_review_table(status: LineStatus, review: LineReview) -> None:
    expected = status is not LineStatus.SOURCE_FOUND and review is LineReview.PENDING
    assert needs_review(line("e1-D1", status=status, review=review)) is expected


def test_unresolved_line_ids_in_draft_order() -> None:
    draft = FdarDraft(
        entries=[
            entry(
                "e1",
                line("e1-D1", status=LineStatus.NUMBER_MISMATCH),
                line("e1-D2"),
                line("e1-D3", status=LineStatus.NO_SOURCE, review=LineReview.REMOVED),
            ),
            entry("e2", line("e2-D1", status=LineStatus.NO_SOURCE)),
        ]
    )
    assert unresolved_line_ids(draft) == ["e1-F", "e1-D1", "e2-F", "e2-D1"]


def test_line_ids_are_unique_in_a_draft() -> None:
    with pytest.raises(ValidationError, match="unique"):
        FdarDraft(entries=[entry("e1", line("x")), entry("e2", line("x"))])


def test_lines_sit_in_their_own_section() -> None:
    with pytest.raises(ValidationError, match="section"):
        FdarEntry(
            focus=line("e1-F", FdarSection.FOCUS),
            data=[line("e1-A1", FdarSection.ACTION)],
            action=[],
            response=[],
        )


def test_draft_needs_an_entry() -> None:
    with pytest.raises(ValidationError):
        FdarDraft(entries=[])


@pytest.mark.parametrize("text", ["", "   \n", "x" * 4001])
def test_rough_note_text_limits_refuse(text: str) -> None:
    with pytest.raises(ValidationError):
        rough_note(text)


def test_rough_note_text_limit_counts_code_points() -> None:
    assert len(rough_note("😀" * 4000).text) == 4000


def test_rough_note_keeps_its_shift_snapshot_in_utc() -> None:
    note = rough_note()
    assert note.shift.code == "10-6"
    assert note.shift.starts_at.tzinfo is UTC
    assert note.shift.shift_date == date(2026, 11, 11)


def test_rough_note_written_at_must_be_aware() -> None:
    with pytest.raises(ValidationError):
        RoughNote.model_validate(rough_note().model_dump() | {"written_at": datetime(2026, 1, 1)})


def test_note_status_matches_signature_and_discard() -> None:
    draft = FdarDraft(entries=[entry("e1")])
    base: dict[str, Any] = {
        "id": uuid4(),
        "rough_note_id": uuid4(),
        "encounter_id": uuid4(),
        "version": 1,
        "draft": draft,
        "checklist": [],
        "generation": generation(),
    }
    signature = Signature(signed_by=uuid4(), signed_at=WRITTEN, content_hash="a" * 64)
    discard = Discard(discarded_by=uuid4(), discarded_at=WRITTEN)
    Note(**base, status=NoteStatus.DRAFT, signature=None, discard=None)
    Note(**base, status=NoteStatus.SIGNED, signature=signature, discard=None)
    Note(**base, status=NoteStatus.DISCARDED, signature=None, discard=discard)
    for status, sig, gone in (
        (NoteStatus.DRAFT, signature, None),
        (NoteStatus.SIGNED, None, None),
        (NoteStatus.DISCARDED, None, None),
        (NoteStatus.SIGNED, signature, discard),
    ):
        with pytest.raises(ValidationError):
            Note(**base, status=status, signature=sig, discard=gone)


def test_signature_hash_is_64_lowercase_hex() -> None:
    with pytest.raises(ValidationError):
        Signature(signed_by=uuid4(), signed_at=WRITTEN, content_hash="A" * 64)


def test_checklist_item_shape() -> None:
    item = ChecklistItem(
        rule=ChecklistRule.FALL_RISK, subject="Fall risk", missing=True, note_span=None
    )
    assert item.model_dump(mode="json")["rule"] == "fall_risk"
    assert "code_status" not in {rule.value for rule in ChecklistRule}


def test_job_failure_only_when_failed_and_note_only_when_succeeded() -> None:
    now = datetime(2026, 11, 12, tzinfo=UTC)
    base: dict[str, Any] = {
        "id": uuid4(),
        "rough_note_id": uuid4(),
        "created_at": now,
        "updated_at": now,
    }
    DraftJob(**base, status=JobStatus.QUEUED, failure=None, note_id=None)
    DraftJob(**base, status=JobStatus.SUCCEEDED, failure=None, note_id=uuid4())
    DraftJob(**base, status=JobStatus.FAILED, failure=JobFailure.AI_BUDGET_REACHED, note_id=None)
    for status, failure, note_id in (
        (JobStatus.QUEUED, JobFailure.MODEL_REFUSED, None),
        (JobStatus.FAILED, None, None),
        (JobStatus.SUCCEEDED, None, None),
        (JobStatus.RUNNING, None, uuid4()),
    ):
        with pytest.raises(ValidationError):
            DraftJob(**base, status=status, failure=failure, note_id=note_id)


def test_allergies_none_is_not_recorded_and_empty_is_nkda() -> None:
    def context(allergies: list[str] | None) -> PatientContext:
        return PatientContext(
            allergies=allergies,
            code_status="Full code",
            lines_tubes=[],
            medicines_due=[],
            pending_tests=[],
            latest_vitals=None,
            fall_risk=None,
        )

    assert context(None).allergies_recorded is False
    assert context([]).allergies_recorded is True
    assert context(["penicillin"]).allergies_recorded is True


def test_patient_identity_is_region_neutral() -> None:
    identity = PatientIdentity(
        given_name="Demo",
        middle_name=None,
        family_name="Patient",
        suffix=None,
        nicknames=[],
        relatives=[Relative(name="Demo Relative", relation="daughter")],
        record_number="SYN-US-0001",
        birth_date=date(1948, 1, 1),
        address=None,
        postal_code=None,
    )
    assert identity.relatives[0].relation == "daughter"


def test_model_output_schema_has_no_enum_const_or_pattern() -> None:
    def keys(node: object) -> set[str]:
        if isinstance(node, dict):
            items: dict[str, object] = node  # pyright: ignore[reportUnknownVariableType]
            return set(items) | {k for value in items.values() for k in keys(value)}
        if isinstance(node, list):
            values: list[object] = node  # pyright: ignore[reportUnknownVariableType]
            return {k for value in values for k in keys(value)}
        return set()

    schema = ModelFdarDraft.model_json_schema()
    assert keys(schema).isdisjoint({"enum", "const", "pattern"})


def test_draft_request_names_the_redacted_text() -> None:
    request = DraftRequest(
        redacted_text="[PATIENT] c/o hilo",
        note_format=NoteFormat.FDAR,
        locale=Locale.EN_PH,
        prompt_version="fdar-v1",
    )
    assert request.model_dump(mode="json")["locale"] == "en-PH"


def test_only_admin_edits_settings_and_only_nurses_write_notes() -> None:
    assert [can_edit_settings(role) for role in Role] == [False, False, True]
    assert [can_write_notes(role) for role in Role] == [True, True, False]


def test_admin_sees_every_facility_and_a_nurse_only_her_own() -> None:
    assert can_see_facility(Role.ADMIN, None, "us-demo") is True
    assert can_see_facility(Role.STAFF_NURSE, "ph-demo", "ph-demo") is True
    assert can_see_facility(Role.HEAD_NURSE, "ph-demo", "us-demo") is False
    assert can_see_facility(Role.STAFF_NURSE, None, "ph-demo") is False


def test_uuid_fields_are_uuids() -> None:
    note = rough_note()
    assert isinstance(note.id, UUID)
    assert note.written_at.utcoffset() == timedelta(hours=8)


def test_review_incomplete_keeps_the_line_ids_and_only_counts_them() -> None:
    error = ReviewIncomplete(["e1-D2", "e1-A2"])
    assert error.line_ids == ["e1-D2", "e1-A2"]
    assert str(error) == "2 line(s) need review"
