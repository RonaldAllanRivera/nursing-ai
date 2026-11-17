import hashlib
import json
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, Request, Response
from nursing_core.domain.notes import RoughNote
from nursing_core.storage.notes import DailyCapReached

from nursing_api.deps import (
    ClockDep,
    NotesDep,
    Nurse,
    NurseDep,
    PatientsDep,
    QueueDep,
    ensure_own_facility,
)
from nursing_api.problems import (
    DailyDraftLimit,
    HeaderRefused,
    PreconditionRequired,
    problems,
)
from nursing_api.routes import CSRF, SIGNED_IN, location_header
from nursing_api.routes.jobs import job_out
from nursing_api.schemas import DraftJobOut, RoughNoteIn

# A longer key would pass Postgres's index-row limit and end as a plain 500.
MAX_IDEMPOTENCY_KEY = 200

router = APIRouter(prefix="/api/v1", tags=["notes"], dependencies=SIGNED_IN)
# A new job counts toward the person's daily draft cap (429).
POSTED = {202: {"headers": location_header("The draft job to poll")}}


def daily_cap_for(request: Request, nurse: Nurse) -> int | None:
    """The daily draft cap that applies to this nurse, or None.

    Demo personas draft from replays at no cost, so only an invited nurse is capped.
    """
    cap: int | None = request.app.state.settings.ai_daily_drafts_per_user
    return None if nurse.user.persona else cap


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
    "/patients/{patient_id}/rough-notes",
    status_code=202,
    response_model=DraftJobOut,
    responses={**POSTED, **problems(401, 403, 404, 422, 423, 428, 429)},
    dependencies=CSRF,
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
    request: Request,
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
    try:
        # A repeat of an earlier request makes no new job, so it is answered even at the cap.
        stored, job = await notes.add_rough_note(
            rough,
            idempotency_key,
            body_hash(patient_id, body.text),
            daily_cap=daily_cap_for(request, nurse),
        )
    except DailyCapReached:
        raise DailyDraftLimit from None
    if stored.id == rough.id:  # a repeat of an earlier request gets that request's job, once
        await queue.enqueue(job.id)
    response.headers["Location"] = f"/api/v1/draft-jobs/{job.id}"
    return job_out(job)


@router.post(
    "/rough-notes/{rough_note_id}/draft-jobs",
    status_code=202,
    response_model=DraftJobOut,
    responses={**POSTED, **problems(401, 403, 404, 409, 422, 423, 429)},
    dependencies=CSRF,
)
async def draft_again(
    rough_note_id: UUID,
    response: Response,
    nurse: NurseDep,
    clock: ClockDep,
    patients: PatientsDep,
    notes: NotesDep,
    queue: QueueDep,
    request: Request,
) -> DraftJobOut:
    """Try drafting again: a new job after a retryable failure; the open job if one is running."""
    rough = await notes.get_rough_note(rough_note_id)
    ensure_own_facility(nurse, await patients.get_patient_by_encounter(rough.encounter_id))
    try:
        job, is_new = await notes.redraft(
            rough_note_id, nurse.user.id, clock.now(), daily_cap=daily_cap_for(request, nurse)
        )
    except DailyCapReached:
        raise DailyDraftLimit from None
    if is_new:
        await queue.enqueue(job.id)
    response.headers["Location"] = f"/api/v1/draft-jobs/{job.id}"
    return job_out(job)
