from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Response
from nursing_core.domain.errors import NoteLocked, StaleVersion
from nursing_core.domain.notes import Discard, Note, NoteStatus, RoughNote
from nursing_core.domain.patient import PatientRecord
from nursing_core.storage.signing import signed_record

from nursing_api.deps import (
    ClockDep,
    NotesDep,
    NurseDep,
    PatientsDep,
    ensure_own_facility,
)
from nursing_api.line_actions import apply_line_action
from nursing_api.problems import PreconditionRequired, problems
from nursing_api.routes import CSRF, SIGNED_IN, etag_header
from nursing_api.schemas import LineAction, NoteOut, RoughNoteOut, SignNoteIn

router = APIRouter(prefix="/api/v1/notes", tags=["notes"], dependencies=SIGNED_IN)

IfMatch = Annotated[
    str | None, Header(alias="If-Match", description="Required: 428 without it, 412 when stale")
]
CHANGE = {200: {"headers": etag_header()}, **problems(401, 403, 404, 409, 412, 422, 423, 428)}


@dataclass(frozen=True)
class Found:
    """A note the nurse may see, with its rough note and patient."""

    note: Note
    rough: RoughNote
    patient: PatientRecord


def etag(version: int) -> str:
    return f'"v{version}"'


def note_out(note: Note, rough: RoughNote, patient: PatientRecord) -> NoteOut:
    return NoteOut(
        **note.model_dump(),
        rough_note=RoughNoteOut(
            id=rough.id,
            text=rough.text,
            written_at=rough.written_at,
            shift=rough.shift,
            note_format=rough.note_format,
        ),
        patient=patient.summary,
    )


def answer(response: Response, found: Found, note: Note) -> NoteOut:
    response.headers["ETag"] = etag(note.version)
    return note_out(note, found.rough, found.patient)


async def find_note(
    note_id: UUID, nurse: NurseDep, notes: NotesDep, patients: PatientsDep
) -> Found:
    """The note, or 404: a note of another facility looks like no note at all (ids are opaque)."""
    note = await notes.get_note(note_id)
    patient = await patients.get_patient_by_encounter(note.encounter_id)
    ensure_own_facility(nurse, patient)
    return Found(note, await notes.get_rough_note(note.rough_note_id), patient)


def check_current(note: Note, if_match: str) -> None:
    """Locked before stale. Only the exact current ETag passes; a malformed one is stale."""
    if note.status is not NoteStatus.DRAFT:
        raise NoteLocked("only a draft can change")
    if if_match != etag(note.version):
        raise StaleVersion("the note has changed")


@router.get(
    "/{note_id}",
    response_model=NoteOut,
    responses={200: {"headers": etag_header()}, **problems(401, 403, 404, 422, 423)},
)
async def get_note(
    note_id: UUID, response: Response, nurse: NurseDep, notes: NotesDep, patients: PatientsDep
) -> NoteOut:
    found = await find_note(note_id, nurse, notes, patients)
    return answer(response, found, found.note)


@router.patch(
    "/{note_id}/lines/{line_id}", response_model=NoteOut, responses=CHANGE, dependencies=CSRF
)
async def act_on_line(
    note_id: UUID,
    line_id: str,
    action: LineAction,
    response: Response,
    nurse: NurseDep,
    notes: NotesDep,
    patients: PatientsDep,
    if_match: IfMatch = None,
) -> NoteOut:
    """Confirm, edit, remove or restore one draft line."""
    if not if_match:
        raise PreconditionRequired
    found = await find_note(note_id, nurse, notes, patients)
    check_current(found.note, if_match)
    draft = apply_line_action(
        found.note.draft,
        line_id,
        action,
        found.rough.text,
        found.patient.facility.units,  # the units in force now, not when the note was drafted
    )
    if draft == found.note.draft:  # nothing changed: no new version
        return answer(response, found, found.note)
    saved = await notes.save_draft(
        found.note.model_copy(update={"draft": draft}), found.note.version
    )
    return answer(response, found, saved)


@router.post("/{note_id}/sign", response_model=NoteOut, responses=CHANGE, dependencies=CSRF)
async def sign_note(
    note_id: UUID,
    body: SignNoteIn,
    response: Response,
    nurse: NurseDep,
    clock: ClockDep,
    notes: NotesDep,
    patients: PatientsDep,
    if_match: IfMatch = None,
) -> NoteOut:
    """Signs the draft with the nurse's PIN: 409 review_incomplete lists the lines that still
    need her."""
    if not if_match:
        raise PreconditionRequired
    found = await find_note(note_id, nurse, notes, patients)
    check_current(found.note, if_match)
    # Raises ReviewIncomplete (409, with the line ids) while any line still needs the nurse.
    record = signed_record(found.note, found.rough, nurse.user.id, clock.now())
    saved = await notes.sign(found.note.id, found.note.version, record)
    return answer(response, found, saved)


@router.post("/{note_id}/discard", response_model=NoteOut, responses=CHANGE, dependencies=CSRF)
async def discard_note(
    note_id: UUID,
    response: Response,
    nurse: NurseDep,
    clock: ClockDep,
    notes: NotesDep,
    patients: PatientsDep,
    if_match: IfMatch = None,
) -> NoteOut:
    """Discards the draft; it never enters the record."""
    if not if_match:
        raise PreconditionRequired
    found = await find_note(note_id, nurse, notes, patients)
    check_current(found.note, if_match)
    discard = Discard(discarded_by=nurse.user.id, discarded_at=clock.now())
    saved = await notes.discard(found.note.id, found.note.version, discard)
    return answer(response, found, saved)
