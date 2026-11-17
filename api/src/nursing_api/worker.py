"""The in-process draft worker: a queue of asyncio tasks and the job that runs core's pipeline.

Nothing here logs note text, names or error messages: only the job id and the error's class.
"""

import asyncio
from collections.abc import Awaitable, Callable
from uuid import UUID, uuid4

import structlog
from nursing_core.domain.errors import (
    AiBudgetReached,
    DatabaseWaking,
    InvalidModelOutput,
    ModelRefused,
    NotFound,
    ReplayMissing,
)
from nursing_core.domain.jobs import JobFailure
from nursing_core.domain.notes import Note, NoteStatus, RoughNote
from nursing_core.pipeline.fdar import run_fdar_pipeline
from nursing_core.ports import Clock
from nursing_core.storage.repositories import (
    PgNoteRepository,
    PgPatientRepository,
    PgUsageRepository,
)

from nursing_api.providers import ProviderFor
from nursing_api.usage import UsageRecorder

# Claim attempts in all while the database wakes. Each one already waits up to the connect
# timeout, so there is no sleep between them; after the last the error goes back to the queue.
CLAIM_ATTEMPTS = 3

log = structlog.get_logger("nursing_api.worker")

FAILURES: dict[type[Exception], JobFailure] = {
    AiBudgetReached: JobFailure.AI_BUDGET_REACHED,
    ModelRefused: JobFailure.MODEL_REFUSED,
    InvalidModelOutput: JobFailure.INVALID_OUTPUT,
    ReplayMissing: JobFailure.REPLAY_MISSING,
}


def failure_for(error: Exception) -> JobFailure:
    """The job failure for an error. Provider outages, PHI leaks and anything unexpected are
    all `provider_error`."""
    for kind, failure in FAILURES.items():
        if isinstance(error, kind):
            return failure
    return JobFailure.PROVIDER_ERROR


class DraftWorker:
    """Runs one draft job: claim it, run the pipeline, save the note."""

    def __init__(
        self,
        notes: PgNoteRepository,
        patients: PgPatientRepository,
        usage: PgUsageRepository,
        clock: Clock,
        provider_for: ProviderFor,
    ) -> None:
        self._notes = notes
        self._patients = patients
        self._usage = usage
        self._clock = clock
        self._provider_for = provider_for

    async def run(self, job_id: UUID) -> None:
        rough = await self._claim(job_id)
        if rough is None:
            return  # another worker has it, or it is already done
        try:
            note = await self._draft(job_id, rough)
        except Exception as error:
            log.warning("draft job failed", job_id=str(job_id), error_class=type(error).__name__)
            await self._fail(job_id, failure_for(error))
            return
        try:
            await self._notes.complete_job(job_id, note)
        except NotFound:
            return  # the job was failed or finished by someone else: nothing to do
        except Exception as error:
            log.error("draft not saved", job_id=str(job_id), error_class=type(error).__name__)
            await self._fail(job_id, JobFailure.PROVIDER_ERROR)

    async def _claim(self, job_id: UUID) -> RoughNote | None:
        for attempt in range(1, CLAIM_ATTEMPTS):
            try:
                return await self._notes.claim_job(job_id)
            except DatabaseWaking:
                log.warning("database waking", job_id=str(job_id), attempts=attempt)
        return await self._notes.claim_job(job_id)  # the last attempt: let the error go

    async def _draft(self, job_id: UUID, rough: RoughNote) -> Note:
        patient = await self._patients.get_patient_by_encounter(rough.encounter_id)
        shift_notes = await self._notes.shift_rough_notes(rough.encounter_id, rough.shift)
        provider = UsageRecorder(self._provider_for(patient), self._usage, self._clock, job_id)
        result = await run_fdar_pipeline(rough, patient, shift_notes, provider)
        return Note(
            id=uuid4(),
            rough_note_id=rough.id,
            encounter_id=rough.encounter_id,
            status=NoteStatus.DRAFT,
            version=1,
            draft=result.draft,
            checklist=result.checklist,
            generation=result.generation,
            signature=None,
            discard=None,
        )

    async def _fail(self, job_id: UUID, failure: JobFailure) -> None:
        try:
            await self._notes.fail_job(job_id, failure)
        except NotFound:
            return  # the job is no longer open
        except Exception as error:
            # Nothing more can be done here; startup recovery fails a job left running.
            log.error(
                "job could not be marked failed",
                job_id=str(job_id),
                error_class=type(error).__name__,
            )


class InProcessQueue:
    """Runs jobs as tracked asyncio tasks. Implements core's `DraftJobQueue`."""

    def __init__(
        self,
        run: Callable[[UUID], Awaitable[None]],
        notes: PgNoteRepository,
    ) -> None:
        self._run = run
        self._notes = notes
        self._tasks: set[asyncio.Task[None]] = set()

    @property
    def pending(self) -> int:
        """How many jobs are still running or waiting."""
        return len(self._tasks)

    async def enqueue(self, job_id: UUID) -> None:
        task = asyncio.create_task(self._guarded(job_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _guarded(self, job_id: UUID) -> None:
        # A task's exception must never go unretrieved (asyncio would log its message).
        try:
            await self._run(job_id)
        except Exception as error:
            log.error("draft job crashed", job_id=str(job_id), error_class=type(error).__name__)

    async def start(self, wait_seconds: float) -> None:
        """After a restart: fail the jobs a crash left running, and run the queued ones again.

        Waits for the database no longer than `wait_seconds`; if it can't be reached the recovery
        is skipped (and logged) so the app still starts and `/health` can say what is wrong.
        """
        try:
            async with asyncio.timeout(wait_seconds):
                await self._notes.fail_running_jobs(JobFailure.PROVIDER_ERROR)
                queued = await self._notes.queued_job_ids()
        except Exception as error:
            log.error("job recovery skipped", error_class=type(error).__name__)
            return
        for job_id in queued:
            await self.enqueue(job_id)

    async def drain(self) -> None:
        """Wait until every job, including ones queued meanwhile, has finished."""
        while self._tasks:
            await asyncio.gather(*self._tasks)

    async def close(self, wait_seconds: float = 5.0) -> None:
        """Give running jobs a moment to finish, then cancel the rest."""
        if self._tasks:
            _done, unfinished = await asyncio.wait(self._tasks, timeout=wait_seconds)
            for task in unfinished:
                task.cancel()
            await asyncio.gather(*unfinished, return_exceptions=True)
            self._tasks.difference_update(unfinished)
