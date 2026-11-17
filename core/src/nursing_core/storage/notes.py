"""The note repository: rough notes, draft jobs, notes and the signed record.

Every method is one transaction. Domain errors carry fixed messages: a database error's text
echoes row values (note text, keys), so none is ever passed on.
"""

from datetime import timedelta
from typing import NoReturn
from uuid import UUID, uuid4

from sqlalchemy import and_, insert, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from nursing_core.domain.errors import IdempotencyConflict, NoteLocked, NotFound, StaleVersion
from nursing_core.domain.hashing import SignedNote
from nursing_core.domain.jobs import DraftJob, JobFailure, JobStatus, ShiftEntry
from nursing_core.domain.notes import (
    Discard,
    FdarDraft,
    GenerationInfo,
    Note,
    NoteStatus,
    RoughNote,
    Signature,
)
from nursing_core.domain.shifts import ShiftRef
from nursing_core.ports import Clock
from nursing_core.storage import tables
from nursing_core.storage.rows import AnyRow, shift_columns, shift_from_row

_ROUGH = tables.rough_note
_JOB = tables.draft_job
_NOTE = tables.note

# A claim is a lease: the worker's 120 s timeout plus 30 s. A job `running` for longer is taken
# to have died (SQS delivers at least once) and can be claimed again, up to MAX_JOB_ATTEMPTS.
JOB_LEASE = timedelta(seconds=150)
MAX_JOB_ATTEMPTS = 3


def _rough_note(row: AnyRow) -> RoughNote:
    return RoughNote(
        id=row.id,
        encounter_id=row.encounter_id,
        author_id=row.author_id,
        text=row.text,
        written_at=row.written_at,
        shift=shift_from_row(row),
        note_format=row.note_format,
    )


def _job(row: AnyRow) -> DraftJob:
    return DraftJob(
        id=row.id,
        rough_note_id=row.rough_note_id,
        status=JobStatus(row.status),
        failure=JobFailure(row.failure) if row.failure else None,
        note_id=row.note_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _note(row: AnyRow) -> Note:
    return Note(
        id=row.id,
        rough_note_id=row.rough_note_id,
        encounter_id=row.encounter_id,
        status=NoteStatus(row.status),
        version=row.version,
        draft=FdarDraft.model_validate(row.draft),
        checklist=row.checklist,
        generation=GenerationInfo.model_validate(row.generation),
        signature=(
            Signature(
                signed_by=row.signed_by, signed_at=row.signed_at, content_hash=row.content_hash
            )
            if row.status == NoteStatus.SIGNED
            else None
        ),
        discard=(
            Discard(discarded_by=row.discarded_by, discarded_at=row.discarded_at)
            if row.status == NoteStatus.DISCARDED
            else None
        ),
    )


async def _refuse_change(conn: AsyncConnection, note_id: UUID, expected_version: int) -> NoReturn:
    """Explains why a conditional update touched no row: the lock is checked before the version."""
    row = (
        await conn.execute(select(_NOTE.c.status, _NOTE.c.version).where(_NOTE.c.id == note_id))
    ).one_or_none()
    if row is None:
        raise NotFound("no such note")
    if row.status != NoteStatus.DRAFT:
        raise NoteLocked("the note is signed or discarded")
    raise StaleVersion("the note was changed by someone else")


class PgNoteRepository:
    def __init__(self, engine: AsyncEngine, clock: Clock) -> None:
        self._engine = engine
        self._clock = clock

    async def add_rough_note(
        self, note: RoughNote, idempotency_key: str, body_hash: str
    ) -> tuple[RoughNote, DraftJob]:
        now = self._clock.now()
        async with self._engine.begin() as conn:
            inserted = await conn.execute(
                pg_insert(_ROUGH)
                .values(
                    id=note.id,
                    encounter_id=note.encounter_id,
                    author_id=note.author_id,
                    text=note.text,
                    written_at=note.written_at,
                    note_format=note.note_format.value,
                    idempotency_key=idempotency_key,
                    body_hash=body_hash,
                    **shift_columns(note.shift),
                )
                .on_conflict_do_nothing(index_elements=["author_id", "idempotency_key"])
                .returning(*_ROUGH.c)
            )
            stored = inserted.one_or_none()
            if stored is not None:
                job_row = (
                    await conn.execute(
                        insert(_JOB)
                        .values(
                            id=uuid4(),
                            rough_note_id=note.id,
                            status=JobStatus.QUEUED.value,
                            created_at=now,
                            updated_at=now,
                        )
                        .returning(*_JOB.c)
                    )
                ).one()
                return _rough_note(stored), _job(job_row)
            # The key was used before (maybe a moment ago, by a request still committing).
            existing = (
                await conn.execute(
                    select(_ROUGH).where(
                        _ROUGH.c.author_id == note.author_id,
                        _ROUGH.c.idempotency_key == idempotency_key,
                    )
                )
            ).one()
            if existing.body_hash != body_hash:
                raise IdempotencyConflict("the idempotency key was used for another request")
            job_row = (
                await conn.execute(select(_JOB).where(_JOB.c.rough_note_id == existing.id))
            ).one()
            return _rough_note(existing), _job(job_row)

    async def get_rough_note(self, rough_note_id: UUID) -> RoughNote:
        async with self._engine.begin() as conn:
            row = (
                await conn.execute(select(_ROUGH).where(_ROUGH.c.id == rough_note_id))
            ).one_or_none()
        if row is None:
            raise NotFound("no such rough note")
        return _rough_note(row)

    async def get_job(self, job_id: UUID) -> DraftJob:
        async with self._engine.begin() as conn:
            row = (await conn.execute(select(_JOB).where(_JOB.c.id == job_id))).one_or_none()
        if row is None:
            raise NotFound("no such job")
        return _job(row)

    async def claim_job(self, job_id: UUID) -> RoughNote | None:
        """Claims a queued job, or a running one whose lease ran out, and adds an attempt.

        The claim that would be the fourth fails the job (`provider_error`) and returns None.
        """
        now = self._clock.now()
        async with self._engine.begin() as conn:
            claimed = (
                await conn.execute(
                    update(_JOB)
                    .where(
                        _JOB.c.id == job_id,
                        or_(
                            _JOB.c.status == JobStatus.QUEUED.value,
                            and_(
                                _JOB.c.status == JobStatus.RUNNING.value,
                                or_(
                                    _JOB.c.claimed_at.is_(None),
                                    _JOB.c.claimed_at < now - JOB_LEASE,
                                ),
                            ),
                        ),
                    )
                    .values(
                        status=JobStatus.RUNNING.value,
                        claimed_at=now,
                        attempts=_JOB.c.attempts + 1,
                        updated_at=now,
                    )
                    .returning(_JOB.c.rough_note_id, _JOB.c.attempts)
                )
            ).one_or_none()
            if claimed is None:
                return None
            if claimed.attempts > MAX_JOB_ATTEMPTS:
                await conn.execute(
                    update(_JOB)
                    .where(_JOB.c.id == job_id)
                    .values(
                        status=JobStatus.FAILED.value,
                        failure=JobFailure.PROVIDER_ERROR.value,
                        updated_at=now,
                    )
                )
                return None
            row = (
                await conn.execute(select(_ROUGH).where(_ROUGH.c.id == claimed.rough_note_id))
            ).one()
            return _rough_note(row)

    async def complete_job(self, job_id: UUID, note: Note) -> None:
        """Stores the note and marks the running job succeeded. Raises NotFound otherwise."""
        now = self._clock.now()
        async with self._engine.begin() as conn:
            job = (
                await conn.execute(select(_JOB).where(_JOB.c.id == job_id).with_for_update())
            ).one_or_none()
            if job is None or job.status != JobStatus.RUNNING.value:
                raise NotFound("no running job")
            if job.rough_note_id != note.rough_note_id:
                raise ValueError("the note is not this job's own")
            await conn.execute(
                insert(_NOTE).values(
                    id=note.id,
                    rough_note_id=note.rough_note_id,
                    encounter_id=note.encounter_id,
                    status=note.status.value,
                    version=note.version,
                    draft=note.draft.model_dump(mode="json"),
                    checklist=[item.model_dump(mode="json") for item in note.checklist],
                    generation=note.generation.model_dump(mode="json"),
                    created_at=now,
                    updated_at=now,
                )
            )
            await conn.execute(
                update(_JOB)
                .where(_JOB.c.id == job_id)
                .values(status=JobStatus.SUCCEEDED.value, note_id=note.id, updated_at=now)
            )

    async def fail_job(self, job_id: UUID, failure: JobFailure) -> None:
        """Marks a queued or running job failed. Raises NotFound if there is no such open job."""
        async with self._engine.begin() as conn:
            failed = await conn.scalar(
                update(_JOB)
                .where(
                    _JOB.c.id == job_id,
                    _JOB.c.status.in_([JobStatus.QUEUED.value, JobStatus.RUNNING.value]),
                )
                .values(
                    status=JobStatus.FAILED.value,
                    failure=failure.value,
                    updated_at=self._clock.now(),
                )
                .returning(_JOB.c.id)
            )
        if failed is None:
            raise NotFound("no open job")

    async def queued_job_ids(self) -> list[UUID]:
        """Every queued job, oldest first: the worker re-enqueues them at startup."""
        async with self._engine.begin() as conn:
            rows = await conn.scalars(
                select(_JOB.c.id)
                .where(_JOB.c.status == JobStatus.QUEUED.value)
                .order_by(_JOB.c.created_at, _JOB.c.id)
            )
            return list(rows)

    async def fail_running_jobs(self, failure: JobFailure) -> int:
        """Fails every running job (a crash left it) and returns how many there were."""
        async with self._engine.begin() as conn:
            rows = await conn.scalars(
                update(_JOB)
                .where(_JOB.c.status == JobStatus.RUNNING.value)
                .values(
                    status=JobStatus.FAILED.value,
                    failure=failure.value,
                    updated_at=self._clock.now(),
                )
                .returning(_JOB.c.id)
            )
            return len(rows.all())

    async def shift_rough_notes(self, encounter_id: UUID, shift: ShiftRef) -> list[RoughNote]:
        async with self._engine.begin() as conn:
            return [_rough_note(row) for row in await self._shift_rows(conn, encounter_id, shift)]

    async def shift_entries(self, encounter_id: UUID, shift: ShiftRef) -> list[ShiftEntry]:
        async with self._engine.begin() as conn:
            rough_rows = await self._shift_rows(conn, encounter_id, shift)
            ids = [row.id for row in rough_rows]
            jobs = {
                row.rough_note_id: _job(row)
                for row in await conn.execute(select(_JOB).where(_JOB.c.rough_note_id.in_(ids)))
            }
            statuses = {
                row.rough_note_id: NoteStatus(row.status)
                for row in await conn.execute(
                    select(_NOTE.c.rough_note_id, _NOTE.c.status).where(
                        _NOTE.c.rough_note_id.in_(ids)
                    )
                )
            }
        return [
            ShiftEntry(
                rough_note=_rough_note(row), job=jobs[row.id], note_status=statuses.get(row.id)
            )
            for row in rough_rows
        ]

    @staticmethod
    async def _shift_rows(
        conn: AsyncConnection, encounter_id: UUID, shift: ShiftRef
    ) -> list[AnyRow]:
        result = await conn.execute(
            select(_ROUGH)
            .where(
                _ROUGH.c.encounter_id == encounter_id,
                _ROUGH.c.shift_code == shift.code,
                _ROUGH.c.shift_starts_at == shift.starts_at,
            )
            .order_by(_ROUGH.c.written_at, _ROUGH.c.id)
        )
        return list(result.all())

    async def get_note(self, note_id: UUID) -> Note:
        async with self._engine.begin() as conn:
            row = (await conn.execute(select(_NOTE).where(_NOTE.c.id == note_id))).one_or_none()
        if row is None:
            raise NotFound("no such note")
        return _note(row)

    async def _change_draft(
        self, conn: AsyncConnection, note_id: UUID, expected_version: int, **values: object
    ) -> AnyRow:
        """The one conditional update behind save, sign and discard: a draft at this version."""
        row = (
            await conn.execute(
                update(_NOTE)
                .where(
                    _NOTE.c.id == note_id,
                    _NOTE.c.version == expected_version,
                    _NOTE.c.status == NoteStatus.DRAFT.value,
                )
                .values(version=expected_version + 1, updated_at=self._clock.now(), **values)
                .returning(*_NOTE.c)
            )
        ).one_or_none()
        if row is None:
            await _refuse_change(conn, note_id, expected_version)
        return row

    async def save_draft(self, note: Note, expected_version: int) -> Note:
        async with self._engine.begin() as conn:
            row = await self._change_draft(
                conn,
                note.id,
                expected_version,
                draft=note.draft.model_dump(mode="json"),
                checklist=[item.model_dump(mode="json") for item in note.checklist],
            )
            return _note(row)

    async def sign(self, note_id: UUID, expected_version: int, record: SignedNote) -> Note:
        """Locks the note as signed and writes its record in one step, the only way to make one."""
        if record.note_id != note_id:
            raise ValueError("the record is for another note")
        signature = record.signature
        async with self._engine.begin() as conn:
            row = await self._change_draft(
                conn,
                note_id,
                expected_version,
                status=NoteStatus.SIGNED.value,
                signed_by=signature.signed_by,
                signed_at=signature.signed_at,
                content_hash=signature.content_hash,
            )
            await conn.execute(
                insert(tables.note_version).values(
                    id=uuid4(),
                    note_id=note_id,
                    version=row.version,
                    content=record.content.model_dump(mode="json"),
                    content_hash=signature.content_hash,
                    signed_by=signature.signed_by,
                    signed_at=signature.signed_at,
                )
            )
            return _note(row)

    async def discard(self, note_id: UUID, expected_version: int, discard: Discard) -> Note:
        async with self._engine.begin() as conn:
            row = await self._change_draft(
                conn,
                note_id,
                expected_version,
                status=NoteStatus.DISCARDED.value,
                discarded_by=discard.discarded_by,
                discarded_at=discard.discarded_at,
            )
            return _note(row)
