"""What a signature covers, and how it is hashed.

Canonical JSON: `model_dump(mode="json")`, keys sorted, no spaces, UTF-8 kept as UTF-8. The audit
chain and amendments will hash these same bytes, so this never changes for a signed record.
"""

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, field_validator

from nursing_core.domain import DomainModel
from nursing_core.domain.errors import NoteLocked
from nursing_core.domain.facility import NoteFormat
from nursing_core.domain.notes import (
    ChecklistItem,
    DraftLine,
    FdarEntry,
    LineReview,
    Note,
    NoteStatus,
    RoughNote,
    Signature,
)
from nursing_core.domain.shifts import ShiftRef


class SignedContent(DomainModel):
    note_id: UUID
    rough_note_id: UUID
    rough_note_text: str
    encounter_id: UUID
    shift: ShiftRef
    note_format: NoteFormat
    entries: list[FdarEntry]  # removed lines left out
    checklist: list[ChecklistItem]
    signed_by: UUID
    signed_at: AwareDatetime

    @field_validator("signed_at")
    @classmethod
    def _in_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class SignedNote(DomainModel):
    note_id: UUID
    content: SignedContent
    signature: Signature


def _kept(entry: FdarEntry) -> FdarEntry:
    """The entry without its removed lines. A focus line can't be removed."""

    def keep(lines: list[DraftLine]) -> list[DraftLine]:
        return [line for line in lines if line.review is not LineReview.REMOVED]

    return entry.model_copy(
        update={
            "data": keep(entry.data),
            "action": keep(entry.action),
            "response": keep(entry.response),
        }
    )


def signed_content(
    note: Note, rough_note: RoughNote, signed_by: UUID, signed_at: datetime
) -> SignedContent:
    if note.status is not NoteStatus.DRAFT:
        raise NoteLocked("only a draft can be signed")
    if note.rough_note_id != rough_note.id:
        raise ValueError("the rough note isn't this note's own")
    return SignedContent(
        note_id=note.id,
        rough_note_id=rough_note.id,
        rough_note_text=rough_note.text,
        encounter_id=note.encounter_id,
        shift=rough_note.shift,
        note_format=rough_note.note_format,
        entries=[_kept(entry) for entry in note.draft.entries],
        checklist=note.checklist,
        signed_by=signed_by,
        signed_at=signed_at,
    )


def canonical_json(model: BaseModel) -> bytes:
    data = model.model_dump(mode="json")
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def content_hash(content: SignedContent) -> str:
    return hashlib.sha256(canonical_json(content)).hexdigest()
