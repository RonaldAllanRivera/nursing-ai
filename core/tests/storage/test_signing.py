"""The pure step before a signature: what a nurse signs is her reviewed lines, hashed."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from nursing_core.demo import DemoCase, load_demo_cases
from nursing_core.domain.errors import ReviewIncomplete
from nursing_core.domain.hashing import canonical_json, content_hash, signed_content
from nursing_core.domain.notes import (
    DraftLine,
    FdarDraft,
    FdarEntry,
    GenerationInfo,
    LineReview,
    Note,
    NoteStatus,
    RoughNote,
    needs_review,
    unresolved_line_ids,
)
from nursing_core.storage.signing import signed_record

CASE: DemoCase = load_demo_cases()[0]
NURSE = uuid4()
NOW = datetime(2026, 11, 12, 1, 0, tzinfo=UTC)


def generation() -> GenerationInfo:
    return GenerationInfo(
        provider="fake",
        model="fake",
        prompt_version="t",
        input_tokens=0,
        output_tokens=0,
        cost_usd=0,  # pyright: ignore[reportArgumentType]
        latency_ms=0,
    )


def draft_note(draft: FdarDraft) -> Note:
    return Note(
        id=uuid4(),
        rough_note_id=CASE.rough_note.id,
        encounter_id=CASE.rough_note.encounter_id,
        status=NoteStatus.DRAFT,
        version=1,
        draft=draft,
        checklist=CASE.expected_checklist,
        generation=generation(),
        signature=None,
        discard=None,
    )


def reviewed(remove: frozenset[str] = frozenset()) -> FdarDraft:
    """The case's draft with every line that needs review confirmed, and the named ones removed."""

    def one(line: DraftLine) -> DraftLine:
        if line.id in remove:
            return line.model_copy(update={"review": LineReview.REMOVED})
        if needs_review(line):
            return line.model_copy(update={"review": LineReview.CONFIRMED})
        return line

    return FdarDraft(
        entries=[
            FdarEntry(
                focus=one(entry.focus),
                data=[one(line) for line in entry.data],
                action=[one(line) for line in entry.action],
                response=[one(line) for line in entry.response],
            )
            for entry in CASE.expected_draft.entries
        ]
    )


def rough() -> RoughNote:
    return CASE.rough_note


def test_a_line_that_needs_review_refuses_the_signature_and_names_it() -> None:
    note = draft_note(CASE.expected_draft)
    expected = unresolved_line_ids(note.draft)
    assert expected
    with pytest.raises(ReviewIncomplete) as refused:
        signed_record(note, rough(), NURSE, NOW)
    assert refused.value.line_ids == expected


def test_a_removed_focus_line_is_refused() -> None:
    draft = reviewed(frozenset({"e1-F"}))
    with pytest.raises(ValueError, match="focus"):
        signed_record(draft_note(draft), rough(), NURSE, NOW)


def test_removed_lines_are_left_out_of_the_record() -> None:
    note = draft_note(reviewed(frozenset({"e1-D1", "e1-A2"})))
    record = signed_record(note, rough(), NURSE, NOW)
    kept = [
        line.id
        for entry in record.content.entries
        for line in (entry.focus, *entry.data, *entry.action, *entry.response)
    ]
    assert "e1-D1" not in kept
    assert "e1-A2" not in kept
    assert "e1-D2" in kept
    assert "Physician notified." not in canonical_json(record.content).decode()


def test_the_record_carries_no_ai_text() -> None:
    draft = reviewed()
    entry = draft.entries[0]
    edited = entry.data[0].model_copy(
        update={"text": "Reports dizziness.", "review": LineReview.EDITED}
    )
    entry = entry.model_copy(update={"data": [edited, *entry.data[1:]]})
    note = draft_note(FdarDraft(entries=[entry, *draft.entries[1:]]))
    record = signed_record(note, rough(), NURSE, NOW)
    text = canonical_json(record.content).decode()
    assert "ai_text" not in text
    assert "Reports dizziness." in text
    assert "Reports dizziness since 2 AM." not in text


def test_the_signature_hash_is_the_hash_of_the_content() -> None:
    note = draft_note(reviewed())
    record = signed_record(note, rough(), NURSE, NOW)
    assert record.note_id == note.id
    assert record.signature.content_hash == content_hash(record.content)
    assert record.content == signed_content(note, rough(), NURSE, NOW)
    assert (record.signature.signed_by, record.signature.signed_at) == (NURSE, NOW)
    assert record.content.rough_note_text == CASE.rough_note.text
