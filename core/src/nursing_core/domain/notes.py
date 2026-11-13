"""Rough notes, FDAR drafts with their checked lines, checklists and notes."""

from collections.abc import Iterator
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    Field,
    NonNegativeInt,
    PositiveInt,
    StringConstraints,
    field_validator,
    model_validator,
)

from nursing_core.domain import DomainModel
from nursing_core.domain.facility import NoteFormat
from nursing_core.domain.shifts import ShiftRef

MAX_NOTE_CHARS = 4000


class Span(DomainModel):
    """[start, end) in code points of the text the nurse typed; the web slices with Array.from."""

    start: NonNegativeInt
    end: PositiveInt

    @model_validator(mode="after")
    def _non_empty(self) -> Self:
        if self.start >= self.end:
            raise ValueError("a span must start before it ends")
        return self


class LineStatus(StrEnum):
    SOURCE_FOUND = "source_found"
    SUMMARY = "summary"
    NUMBER_MISMATCH = "number_mismatch"
    NO_SOURCE = "no_source"


class LineReview(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    EDITED = "edited"
    REMOVED = "removed"


class FdarSection(StrEnum):
    FOCUS = "focus"
    DATA = "data"
    ACTION = "action"
    RESPONSE = "response"


class SourceQuote(DomainModel):
    text: str
    span: Span | None  # None: the quote isn't in the note


class MismatchKind(StrEnum):
    VALUE = "value"
    UNIT = "unit"


class NumberMismatch(DomainModel):
    kind: MismatchKind
    draft_text: str
    draft_span: Span  # into DraftLine.text
    note_text: str | None
    note_span: Span | None  # into RoughNote.text


class DraftLine(DomainModel):
    id: str  # opaque and unique within a note; clients never parse it
    section: FdarSection
    text: str
    ai_text: str
    status: LineStatus
    review: LineReview
    source_quotes: list[SourceQuote]
    number_mismatches: list[NumberMismatch]


class FdarEntry(DomainModel):
    focus: DraftLine
    data: list[DraftLine]
    action: list[DraftLine]
    response: list[DraftLine]

    @model_validator(mode="after")
    def _lines_in_their_sections(self) -> Self:
        groups = (
            (FdarSection.FOCUS, [self.focus]),
            (FdarSection.DATA, self.data),
            (FdarSection.ACTION, self.action),
            (FdarSection.RESPONSE, self.response),
        )
        for section, lines in groups:
            if any(line.section is not section for line in lines):
                raise ValueError(f"every {section.value} line must have section {section.value}")
        return self

    def lines(self) -> Iterator[DraftLine]:
        yield self.focus
        yield from self.data
        yield from self.action
        yield from self.response


class FdarDraft(DomainModel):
    entries: list[FdarEntry] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_line_ids(self) -> Self:
        ids = [line.id for line in self.lines()]
        if len(set(ids)) != len(ids):
            raise ValueError("line ids must be unique within a note")
        return self

    def lines(self) -> Iterator[DraftLine]:
        for entry in self.entries:
            yield from entry.lines()


def needs_review(line: DraftLine) -> bool:
    """A line needs the nurse while it isn't source-found and she hasn't acted on it."""
    return line.status is not LineStatus.SOURCE_FOUND and line.review is LineReview.PENDING


def unresolved_line_ids(draft: FdarDraft) -> list[str]:
    return [line.id for line in draft.lines() if needs_review(line)]


class ChecklistRule(StrEnum):
    """The missing-items rules. Code status is never one of them."""

    ALLERGIES = "allergies"
    LINE_OR_TUBE = "line_or_tube"
    MEDICINE_DUE = "medicine_due"
    PENDING_TEST = "pending_test"
    FALL_RISK = "fall_risk"


class ChecklistItem(DomainModel):
    rule: ChecklistRule
    subject: str
    missing: bool
    note_span: Span | None


class RoughNote(DomainModel):
    id: UUID
    encounter_id: UUID
    author_id: UUID
    text: Annotated[str, StringConstraints(min_length=1, max_length=MAX_NOTE_CHARS)]
    written_at: AwareDatetime
    shift: ShiftRef  # the shift the nurse's session was working, kept as written
    note_format: NoteFormat

    @field_validator("text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("a rough note can't be blank")
        return value


class NoteStatus(StrEnum):
    DRAFT = "draft"
    SIGNED = "signed"
    DISCARDED = "discarded"


class GenerationInfo(DomainModel):
    provider: Literal["fake", "replay", "anthropic"]
    model: str
    prompt_version: str
    input_tokens: NonNegativeInt
    output_tokens: NonNegativeInt
    cost_usd: Annotated[Decimal, Field(ge=0)]
    latency_ms: NonNegativeInt


class Signature(DomainModel):
    signed_by: UUID
    signed_at: AwareDatetime
    content_hash: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class Discard(DomainModel):
    discarded_by: UUID
    discarded_at: AwareDatetime


class Note(DomainModel):
    id: UUID
    rough_note_id: UUID
    encounter_id: UUID
    status: NoteStatus
    version: PositiveInt
    draft: FdarDraft
    checklist: list[ChecklistItem]
    generation: GenerationInfo
    signature: Signature | None
    discard: Discard | None

    @model_validator(mode="after")
    def _status_matches(self) -> Self:
        signed = self.status is NoteStatus.SIGNED
        discarded = self.status is NoteStatus.DISCARDED
        if signed != (self.signature is not None) or discarded != (self.discard is not None):
            raise ValueError("a signed note has a signature and a discarded note a discard, only")
        return self
