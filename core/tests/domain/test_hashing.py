"""What a signature hashes, fixed now so the audit chain and amendments hash the same bytes."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from nursing_core.domain import DomainModel
from nursing_core.domain.errors import NoteLocked
from nursing_core.domain.facility import NoteFormat, preset
from nursing_core.domain.hashing import SignedContent, canonical_json, content_hash, signed_content
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
    SourceQuote,
    Span,
)
from nursing_core.domain.shifts import shift_containing

PH = preset("PH", "ph-demo", "SYNTHETIC Demo Hospital (PH)")
MANILA = ZoneInfo("Asia/Manila")
WRITTEN = datetime(2026, 11, 12, 5, 10, tzinfo=MANILA)
SIGNED_AT = datetime(2026, 11, 12, 5, 30, tzinfo=MANILA)
NURSE = UUID("00000000-0000-4000-8000-000000000001")
TEXT = "pt c/o hilo since 2am. still weak."


def line(line_id: str, section: FdarSection, text: str, review: LineReview) -> DraftLine:
    return DraftLine(
        id=line_id,
        section=section,
        text=text,
        ai_text=text,
        status=LineStatus.SOURCE_FOUND,
        review=review,
        source_quotes=[SourceQuote(text="still weak", span=Span(start=23, end=33))],
        number_mismatches=[],
    )


def rough_note(text: str = TEXT) -> RoughNote:
    return RoughNote(
        id=UUID("00000000-0000-4000-8000-000000000002"),
        encounter_id=UUID("00000000-0000-4000-8000-000000000003"),
        author_id=NURSE,
        text=text,
        written_at=WRITTEN,
        shift=shift_containing(WRITTEN, PH),
        note_format=NoteFormat.FDAR,
    )


def note(status: NoteStatus = NoteStatus.DRAFT) -> Note:
    draft = FdarDraft(
        entries=[
            FdarEntry(
                focus=line("e1-F", FdarSection.FOCUS, "Dizziness", LineReview.CONFIRMED),
                data=[
                    line("e1-D1", FdarSection.DATA, "Still weak.", LineReview.PENDING),
                    line("e1-D2", FdarSection.DATA, "Physician notified.", LineReview.REMOVED),
                ],
                action=[],
                response=[],
            )
        ]
    )
    return Note(
        id=UUID("00000000-0000-4000-8000-000000000004"),
        rough_note_id=UUID("00000000-0000-4000-8000-000000000002"),
        encounter_id=UUID("00000000-0000-4000-8000-000000000003"),
        status=status,
        version=3,
        draft=draft,
        checklist=[
            ChecklistItem(
                rule=ChecklistRule.FALL_RISK, subject="Fall risk", missing=True, note_span=None
            )
        ],
        generation=GenerationInfo(
            provider="fake",
            model="fake",
            prompt_version="fdar-v1",
            input_tokens=0,
            output_tokens=0,
            cost_usd=Decimal(0),
            latency_ms=0,
        ),
        signature=None,
        discard=Discard(discarded_by=NURSE, discarded_at=SIGNED_AT)
        if status is NoteStatus.DISCARDED
        else None,
    )


class Tiny(DomainModel):
    b: str
    a: int


def test_canonical_json_is_sorted_compact_utf8() -> None:
    assert canonical_json(Tiny(b="é ✓", a=1)) == '{"a":1,"b":"é ✓"}'.encode()


def test_signed_content_drops_removed_lines() -> None:
    content = signed_content(note(), rough_note(), NURSE, SIGNED_AT)
    ids = [line.id for entry in content.entries for line in [entry.focus, *entry.data]]
    assert ids == ["e1-F", "e1-D1"]


def test_signed_content_keeps_the_note_the_shift_and_the_signer() -> None:
    content = signed_content(note(), rough_note(), NURSE, SIGNED_AT)
    assert content.note_id == UUID("00000000-0000-4000-8000-000000000004")
    assert content.rough_note_text == TEXT
    assert content.shift.code == "10-6"
    assert content.note_format is NoteFormat.FDAR
    assert content.signed_by == NURSE
    assert content.signed_at == SIGNED_AT


@pytest.mark.parametrize("status", [NoteStatus.SIGNED, NoteStatus.DISCARDED])
def test_only_a_draft_can_be_signed(status: NoteStatus) -> None:
    locked = note(NoteStatus.DISCARDED) if status is NoteStatus.DISCARDED else None
    if locked is None:
        draft = note()
        locked = Note.model_validate(
            draft.model_dump()
            | {
                "status": NoteStatus.SIGNED,
                "signature": {"signed_by": NURSE, "signed_at": SIGNED_AT, "content_hash": "a" * 64},
            }
        )
    with pytest.raises(NoteLocked):
        signed_content(locked, rough_note(), NURSE, SIGNED_AT)


def test_rough_note_must_be_the_notes_own() -> None:
    other = RoughNote.model_validate(
        rough_note().model_dump() | {"id": UUID("00000000-0000-4000-8000-000000000009")}
    )
    with pytest.raises(ValueError, match="rough note"):
        signed_content(note(), other, NURSE, SIGNED_AT)


def test_content_hash_known_vector() -> None:
    content = signed_content(note(), rough_note(), NURSE, SIGNED_AT)
    assert content_hash(content) == (
        "8188d6f0af060da2e3849efe06a513b81c33650b8789ec39dd6bc97a47a5b065"
    )


def test_content_hash_ignores_field_order_and_changes_with_one_character() -> None:
    content = signed_content(note(), rough_note(), NURSE, SIGNED_AT)
    reordered = SignedContent.model_validate(dict(reversed(content.model_dump().items())))
    assert content_hash(reordered) == content_hash(content)
    changed = signed_content(note(), rough_note(TEXT.replace("2am", "3am")), NURSE, SIGNED_AT)
    assert content_hash(changed) != content_hash(content)


def test_signed_at_is_hashed_as_the_same_instant_in_any_zone() -> None:
    manila = signed_content(note(), rough_note(), NURSE, SIGNED_AT)
    utc = signed_content(note(), rough_note(), NURSE, SIGNED_AT.astimezone(UTC))
    assert content_hash(manila) == content_hash(utc)
