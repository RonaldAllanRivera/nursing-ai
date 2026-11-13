"""Request and response bodies of the HTTP API (the domain types are reused where they fit)."""

from typing import Annotated, Literal
from uuid import UUID

from nursing_core.domain.facility import FacilityProfile, FacilitySettings, NoteFormat
from nursing_core.domain.jobs import JobFailure, JobStatus
from nursing_core.domain.notes import (
    MAX_NOTE_CHARS,
    ChecklistItem,
    Discard,
    FdarDraft,
    GenerationInfo,
    NoteStatus,
    Signature,
)
from nursing_core.domain.patient import PatientSummary
from nursing_core.domain.shifts import ShiftRef
from nursing_core.domain.users import Role
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, field_validator

FacilitySettingsIn = FacilitySettings


class In(BaseModel):
    """A request body: unknown fields are refused."""

    model_config = ConfigDict(extra="forbid")


class FacilityOut(BaseModel):
    profile: FacilityProfile
    version: int
    shift_choices: list[ShiftRef]


class PersonaOut(BaseModel):
    id: UUID
    display_name: str
    initials: str
    role: Role
    facility_key: str | None
    facility_name: str | None


class SessionIn(In):
    persona_id: UUID


class SessionOut(BaseModel):
    user_id: UUID
    display_name: str
    initials: str
    role: Role
    facility_key: str | None  # None for the admin, who works across every facility
    shift: ShiftRef | None  # None for the admin, who has no shift


class ShiftChoiceIn(In):
    starts_at: AwareDatetime


class DraftJobOut(BaseModel):
    id: UUID
    rough_note_id: UUID
    status: JobStatus
    failure: JobFailure | None
    note_id: UUID | None


class ShiftNoteOut(BaseModel):
    rough_note_id: UUID
    written_at: AwareDatetime
    job: DraftJobOut
    note_status: NoteStatus | None


class PatientDetail(BaseModel):
    summary: PatientSummary
    shift: ShiftRef
    notes: list[ShiftNoteOut]


class RoughNoteIn(In):
    text: Annotated[str, StringConstraints(min_length=1, max_length=MAX_NOTE_CHARS)]

    @field_validator("text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("a rough note can't be blank")
        return value


class RoughNoteOut(BaseModel):
    id: UUID
    text: str
    written_at: AwareDatetime
    shift: ShiftRef
    note_format: NoteFormat


class NoteOut(BaseModel):
    id: UUID
    rough_note_id: UUID
    encounter_id: UUID
    status: NoteStatus
    version: int
    draft: FdarDraft
    checklist: list[ChecklistItem]
    generation: GenerationInfo
    signature: Signature | None
    discard: Discard | None
    rough_note: RoughNoteOut
    patient: PatientSummary


class ConfirmLine(In):
    action: Literal["confirm"]


class EditLine(In):
    action: Literal["edit"]
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class RemoveLine(In):
    action: Literal["remove"]


class RestoreLine(In):
    action: Literal["restore"]


LineAction = Annotated[
    ConfirmLine | EditLine | RemoveLine | RestoreLine, Field(discriminator="action")
]
