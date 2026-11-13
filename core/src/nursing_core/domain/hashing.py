"""What a signature covers, and how it is hashed.

Canonical JSON: `model_dump(mode="json")`, keys sorted, no spaces, UTF-8 kept as UTF-8. The audit
chain and amendments will hash these same bytes, so this never changes for a signed record.
"""

import hashlib
import json
from datetime import UTC, datetime
from typing import Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, field_validator, model_validator

from nursing_core.domain import DomainModel
from nursing_core.domain.errors import NoteLocked, ReviewIncomplete
from nursing_core.domain.facility import NoteFormat
from nursing_core.domain.notes import (
    ChecklistItem,
    DraftLine,
    FdarSection,
    LineReview,
    LineStatus,
    Note,
    NoteStatus,
    NumberMismatch,
    RoughNote,
    Signature,
    SourceQuote,
    unresolved_line_ids,
)
from nursing_core.domain.shifts import ShiftRef


class SignedLine(DomainModel):
    """A line as signed: the nurse's final text and its checks. The AI's own wording of a line
    the nurse changed is not part of the record."""

    id: str
    section: FdarSection
    text: str
    status: LineStatus
    review: LineReview
    source_quotes: list[SourceQuote]
    number_mismatches: list[NumberMismatch]


class SignedEntry(DomainModel):
    focus: SignedLine
    data: list[SignedLine]
    action: list[SignedLine]
    response: list[SignedLine]


class SignedContent(DomainModel):
    note_id: UUID
    rough_note_id: UUID
    rough_note_text: str
    encounter_id: UUID
    shift: ShiftRef
    note_format: NoteFormat
    entries: list[SignedEntry]  # removed lines left out
    checklist: list[ChecklistItem]
    signed_by: UUID
    signed_at: AwareDatetime

    @field_validator("signed_at")
    @classmethod
    def _in_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class SignedNote(DomainModel):
    """The record a signature writes. Its hash, signer and time must be the content's own."""

    note_id: UUID
    content: SignedContent
    signature: Signature

    @model_validator(mode="after")
    def _signature_matches_content(self) -> Self:
        if self.note_id != self.content.note_id:
            raise ValueError("the signed note must be the content's note")
        if self.signature.content_hash != content_hash(self.content):
            raise ValueError("the signature's hash must be the content's hash")
        if (self.signature.signed_by, self.signature.signed_at) != (
            self.content.signed_by,
            self.content.signed_at,
        ):
            raise ValueError("the signature's signer and time must be the content's")
        return self


def _signed(line: DraftLine) -> SignedLine:
    return SignedLine.model_validate(line.model_dump(exclude={"ai_text"}))


def _kept(lines: list[DraftLine]) -> list[SignedLine]:
    return [_signed(line) for line in lines if line.review is not LineReview.REMOVED]


def signed_content(
    note: Note, rough_note: RoughNote, signed_by: UUID, signed_at: datetime
) -> SignedContent:
    if note.status is not NoteStatus.DRAFT:
        raise NoteLocked("only a draft can be signed")
    if note.rough_note_id != rough_note.id:
        raise ValueError("the rough note isn't this note's own")
    if any(entry.focus.review is LineReview.REMOVED for entry in note.draft.entries):
        raise ValueError("a focus line can't be removed")
    if unresolved := unresolved_line_ids(note.draft):
        raise ReviewIncomplete(unresolved)
    return SignedContent(
        note_id=note.id,
        rough_note_id=rough_note.id,
        rough_note_text=rough_note.text,
        encounter_id=note.encounter_id,
        shift=rough_note.shift,
        note_format=rough_note.note_format,
        entries=[
            SignedEntry(
                focus=_signed(entry.focus),
                data=_kept(entry.data),
                action=_kept(entry.action),
                response=_kept(entry.response),
            )
            for entry in note.draft.entries
        ],
        checklist=note.checklist,
        signed_by=signed_by,
        signed_at=signed_at,
    )


def canonical_json(model: BaseModel) -> bytes:
    data = model.model_dump(mode="json")
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def content_hash(content: SignedContent) -> str:
    return hashlib.sha256(canonical_json(content)).hexdigest()
