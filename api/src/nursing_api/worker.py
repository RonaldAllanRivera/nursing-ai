"""The in-process draft worker: a queue of asyncio tasks and the job that runs core's pipeline.

Nothing here logs note text, names or error messages: only the job id and the error's class.
"""

import asyncio
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Protocol
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
from nursing_core.domain.patient import PatientRecord
from nursing_core.pipeline.fdar import run_fdar_pipeline
from nursing_core.ports import Clock, LlmProvider
from nursing_core.storage.repositories import (
    PgNoteRepository,
    PgPatientRepository,
    PgUsageRepository,
)

from nursing_api.usage import UsageRecorder

# Claim attempts in all while the database wakes. Each one already waits up to the connect
# timeout, so there is no sleep between them; after the last the error goes back to the queue.
CLAIM_ATTEMPTS = 3

# At most this many in-process jobs at once, like the worker's SQS concurrency.
MAX_CONCURRENT_JOBS = 2

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


class JobProviders(Protocol):
    """Gives the provider for one job; `DraftProviders` is the real one."""

    def for_job(self, patient: PatientRecord, *, job_id: UUID, persona: bool) -> LlmProvider: ...


class DraftWorker:
    """Runs one draft job: claim it, run the pipeline, save the note.

    `report_spend` (the worker role's metric) is called once after every job that ran, with what
    the job's AI calls cost: nothing for a replay, a mock answer or a job that failed before a call.
    """

    def __init__(
        self,
        notes: PgNoteRepository,
        patients: PgPatientRepository,
        usage: PgUsageRepository,
        clock: Clock,
        providers: JobProviders,
        report_spend: Callable[[Decimal], None] | None = None,
    ) -> None:
        self._notes = notes
        self._patients = patients
        self._usage = usage
        self._clock = clock
        self._providers = providers
        self._report_spend = report_spend

    async def run(self, job_id: UUID) -> None:
        rough = await self._claim(job_id)
        if rough is None:
            return  # another worker has it, or it is already done
        recorder: UsageRecorder | None = None
        try:
            try:
                patient = await self._patients.get_patient_by_encounter(rough.encounter_id)
                persona = await self._notes.written_by_persona(rough.id)
                recorder = UsageRecorder(
                    self._providers.for_job(patient, job_id=job_id, persona=persona),
                    self._usage,
                    self._clock,
                    job_id,
                )
                note = await self._draft(rough, patient, recorder, persona=persona)
            except Exception as error:
                log.warning(
                    "draft job failed", job_id=str(job_id), error_class=type(error).__name__
                )
                await self._fail(job_id, failure_for(error))
                return
            try:
                await self._notes.complete_job(job_id, note)
            except NotFound:
                return  # the job was failed or finished by someone else: nothing to do
            except Exception as error:
                log.error("draft not saved", job_id=str(job_id), error_class=type(error).__name__)
                await self._fail(job_id, JobFailure.PROVIDER_ERROR)
        finally:
            if self._report_spend is not None:
                self._report_spend(recorder.cost_usd if recorder is not None else Decimal(0))

    async def _claim(self, job_id: UUID) -> RoughNote | None:
        for attempt in range(1, CLAIM_ATTEMPTS):
            try:
                return await self._notes.claim_job(job_id)
            except DatabaseWaking:
                log.warning("database waking", job_id=str(job_id), attempts=attempt)
        return await self._notes.claim_job(job_id)  # the last attempt: let the error go

    async def _draft(
        self, rough: RoughNote, patient: PatientRecord, provider: LlmProvider, *, persona: bool
    ) -> Note:
        # The checklist reads only the shift notes of the draft's own side: personas share the demo
        # facilities with invited staff, and neither may tick off the other's missing items.
        shift_notes = await self._notes.shift_rough_notes(
            rough.encounter_id, rough.shift, persona=persona
        )
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
            # No outcome is recorded, so the job stays running. Raise, so the queue delivers the
            # message again: once its lease has run out the next claim retries the job, or the
            # fourth fails it. (In process, the queue's guard logs this and nothing retries.)
            log.error(
                "job could not be marked failed",
                job_id=str(job_id),
                error_class=type(error).__name__,
            )
            raise


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
        self._slots = asyncio.Semaphore(MAX_CONCURRENT_JOBS)

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
            async with self._slots:
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
