from uuid import UUID

from fastapi import APIRouter
from nursing_core.domain.jobs import DraftJob

from nursing_api.deps import NotesDep, NurseDep, PatientsDep, ensure_own_facility
from nursing_api.problems import problems
from nursing_api.routes import SIGNED_IN
from nursing_api.schemas import DraftJobOut

router = APIRouter(prefix="/api/v1/draft-jobs", tags=["notes"], dependencies=SIGNED_IN)


def job_out(job: DraftJob) -> DraftJobOut:
    return DraftJobOut(
        id=job.id,
        rough_note_id=job.rough_note_id,
        status=job.status,
        failure=job.failure,
        note_id=job.note_id,
    )


@router.get("/{job_id}", response_model=DraftJobOut, responses=problems(401, 403, 404, 422))
async def get_job(
    job_id: UUID, nurse: NurseDep, notes: NotesDep, patients: PatientsDep
) -> DraftJobOut:
    # A job belongs to the facility of its patient: another facility's job is a 404.
    job = await notes.get_job(job_id)
    rough = await notes.get_rough_note(job.rough_note_id)
    ensure_own_facility(nurse, await patients.get_patient_by_encounter(rough.encounter_id))
    return job_out(job)
