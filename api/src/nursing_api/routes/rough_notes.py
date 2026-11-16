import hashlib
import json
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, Response
from nursing_core.domain.notes import RoughNote

from nursing_api.deps import (
    ClockDep,
    NotesDep,
    NurseDep,
    PatientsDep,
    QueueDep,
    ensure_own_facility,
)
from nursing_api.problems import HeaderRefused, PreconditionRequired, problems
from nursing_api.routes import SIGNED_IN
from nursing_api.routes.jobs import job_out
from nursing_api.schemas import DraftJobOut, RoughNoteIn

# A longer key would pass Postgres's index-row limit and end as a plain 500.
MAX_IDEMPOTENCY_KEY = 200

router = APIRouter(prefix="/api/v1/patients", tags=["notes"], dependencies=SIGNED_IN)


def body_hash(patient_id: UUID, text: str) -> str:
    """Identifies a request for the idempotency check: the patient and the text, nothing else."""
    canonical = json.dumps(
        {"patient_id": str(patient_id), "text": text},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


@router.post(
    "/{patient_id}/rough-notes",
    status_code=202,
    response_model=DraftJobOut,
    responses={
        202: {
            "headers": {
                "Location": {"description": "The draft job to poll", "schema": {"type": "string"}}
            }
        },
        **problems(401, 403, 404, 422, 428),
    },
)
async def add_rough_note(
    patient_id: UUID,
    body: RoughNoteIn,
    response: Response,
    nurse: NurseDep,
    clock: ClockDep,
    patients: PatientsDep,
    notes: NotesDep,
    queue: QueueDep,
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description="Required: 428 without it. The same key and text return the first job.",
        ),
    ] = None,
) -> DraftJobOut:
    """Saves the rough note in the session's shift and starts a draft job."""
    if not idempotency_key:
        raise PreconditionRequired
    if len(idempotency_key) > MAX_IDEMPOTENCY_KEY:
        raise HeaderRefused("header.Idempotency-Key", "too long")
    patient = await patients.get_patient(patient_id)
    ensure_own_facility(nurse, patient)
    rough = RoughNote(
        id=uuid4(),
        encounter_id=patient.encounter_id,
        author_id=nurse.user.id,
        text=body.text,
        written_at=clock.now(),
        shift=nurse.shift,  # the session's shift as she signed in, never worked out from the clock
        note_format=patient.facility.default_note_format,
    )
    stored, job = await notes.add_rough_note(
        rough, idempotency_key, body_hash(patient_id, body.text)
    )
    if stored.id == rough.id:  # a repeat of an earlier request gets that request's job, once
        await queue.enqueue(job.id)
    response.headers["Location"] = f"/api/v1/draft-jobs/{job.id}"
    return job_out(job)
