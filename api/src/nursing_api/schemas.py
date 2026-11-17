"""Request and response bodies of the HTTP API (the domain types are reused where they fit)."""

from typing import Annotated, Literal, Self
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
    check_note_text,
)
from nursing_core.domain.patient import PatientSummary
from nursing_core.domain.shifts import ShiftRef
from nursing_core.domain.users import Role, SessionGate, UserStatus
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

FacilitySettingsIn = FacilitySettings
# Six ASCII digits. `\d` would also take other scripts' digits, such as full-width ones.
Pin = Annotated[str, StringConstraints(pattern=r"^[0-9]{6}$")]


class In(BaseModel):
    """A request body: unknown fields are refused, and errors never show the input."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class FacilityUpdateIn(FacilitySettings):
    """A settings save: the settings and the admin's PIN, which proves it is still them."""

    pin: Pin = Field(repr=False)

    def settings(self) -> FacilitySettings:
        """The settings alone: the PIN must never reach the facility's history."""
        return FacilitySettings.model_validate(self.model_dump(exclude={"pin"}))


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


# What GET /api/v1/auth/google/callback sends the browser to /sign-in?error= with:
# no_access: not invited, revoked, an unverified email, or another Google account for this email;
# expired: this browser's sign-in attempt is gone or isn't its own (the state didn't match);
# cancelled: Google answered with an error, such as the person backing out.
SignInError = Literal["no_access", "expired", "cancelled"]


class SignInOptionsOut(BaseModel):
    """What the sign-in page offers. Answered without the database, so a visitor (or a crawler)
    never wakes a paused one."""

    google: bool
    personas: bool
    demo: bool
    demo_pin: str | None  # shown to visitors in the demo; None elsewhere


class SessionIn(In):
    persona_id: UUID


class PinIn(In):
    pin: Pin = Field(repr=False)


class SignNoteIn(PinIn):
    """Signing a note: the nurse's PIN proves it is her at the keyboard."""


class SessionOut(BaseModel):
    user_id: UUID
    display_name: str
    initials: str
    role: Role
    facility_key: str | None  # None for the admin, who works across every facility
    shift: ShiftRef | None  # None for the admin, who has no shift
    kind: Literal["persona", "google"]
    gate: SessionGate  # only `open` reaches patient data; the others name a screen
    csrf_token: str  # sent back in X-CSRF-Token on every POST, PUT, PATCH and DELETE
    expires_at: (
        AwareDatetime  # the facility's session length from sign-in; unlocking never moves it
    )
    idle_lock_seconds: int


class UserOut(BaseModel):
    """A person on the staff list. Demo personas are never listed."""

    id: UUID
    email: str
    display_name: str
    initials: str
    role: Role
    facility_key: str | None  # None for the admin
    status: UserStatus
    pin_locked: bool


class InviteIn(In):
    email: Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, max_length=254)]
    role: Role
    facility_key: str | None  # None for the admin, who works across every facility
    pin: Pin = Field(repr=False)  # the admin's own PIN

    @field_validator("email")
    @classmethod
    def _one_address(cls, value: str) -> str:
        local, _, domain = value.partition("@")
        if value.count("@") != 1 or not local or not domain:
            raise ValueError("must be one email address")
        return value

    @model_validator(mode="after")
    def _admin_alone_has_no_facility(self) -> Self:
        if (self.facility_key is None) != (self.role is Role.ADMIN):
            raise ValueError("an admin has no facility, and every nurse has one")
        return self


class ShiftChoiceIn(In):
    starts_at: AwareDatetime


class DraftJobOut(BaseModel):
    id: UUID
    rough_note_id: UUID
    status: JobStatus
    failure: JobFailure | None
    note_id: UUID | None
    retryable: bool  # failed in a way "Try drafting again" can fix


class ShiftNoteOut(BaseModel):
    rough_note_id: UUID
    written_at: AwareDatetime
    job: DraftJobOut
    note_status: NoteStatus | None


class PatientDetail(BaseModel):
    summary: PatientSummary
    shift: ShiftRef
    notes: list[ShiftNoteOut]
    demo_note: str | None  # a demo patient's rough note, for "Use the demo note"; None otherwise


class RoughNoteIn(In):
    text: Annotated[str, StringConstraints(min_length=1, max_length=MAX_NOTE_CHARS)]

    @field_validator("text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return check_note_text(value)


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

    @field_validator("text")
    @classmethod
    def _no_nul(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("a line can't contain a NUL character")
        return value


class RemoveLine(In):
    action: Literal["remove"]


class RestoreLine(In):
    action: Literal["restore"]


LineAction = Annotated[
    ConfirmLine | EditLine | RemoveLine | RestoreLine, Field(discriminator="action")
]
