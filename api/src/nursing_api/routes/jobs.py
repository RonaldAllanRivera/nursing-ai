from uuid import UUID

import structlog
from fastapi import APIRouter
from nursing_core.domain.jobs import DraftJob, JobStatus, is_retryable

from nursing_api.deps import NotesDep, NurseDep, PatientsDep, QueueDep, ensure_own_facility
from nursing_api.problems import problems
from nursing_api.routes import SIGNED_IN
from nursing_api.schemas import DraftJobOut

router = APIRouter(prefix="/api/v1/draft-jobs", tags=["notes"], dependencies=SIGNED_IN)
log = structlog.get_logger("nursing_api.jobs")


async def resend_stuck(notes: NotesDep, queue: QueueDep, jobs: list[DraftJob]) -> None:
    """Sends again the message of any open job that no worker has taken up.

    Lambda never runs the startup recovery, and a send can be lost (an SQS error, a page that
    went away, a worker that cannot start): the polls that look at a job are what bring it back.
    The database picks the jobs and marks them sent, so a job goes again at most once a minute,
    even when two polls ask at once. A failed send never fails the poll: the next one after the
    minute tries again.
    """
    open_ids = [j.id for j in jobs if j.status in (JobStatus.QUEUED, JobStatus.RUNNING)]
    for job_id in await notes.resend_due(open_ids):
        try:
            await queue.enqueue(job_id)
        except Exception as error:  # the poll answers anyway
            log.warning("job resend failed", job_id=str(job_id), error_class=type(error).__name__)


def job_out(job: DraftJob) -> DraftJobOut:
    return DraftJobOut(
        id=job.id,
        rough_note_id=job.rough_note_id,
        status=job.status,
        failure=job.failure,
        note_id=job.note_id,
        retryable=is_retryable(job.failure),
    )


@router.get("/{job_id}", response_model=DraftJobOut, responses=problems(401, 403, 404, 422, 423))
async def get_job(
    job_id: UUID, nurse: NurseDep, notes: NotesDep, patients: PatientsDep, queue: QueueDep
) -> DraftJobOut:
    # A job belongs to the facility of its patient: another facility's job is a 404.
    job = await notes.get_job(job_id)
    rough = await notes.get_rough_note(job.rough_note_id)
    ensure_own_facility(nurse, await patients.get_patient_by_encounter(rough.encounter_id))
    await resend_stuck(notes, queue, [job])
    return job_out(job)
