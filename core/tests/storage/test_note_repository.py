"""The note repository: rough notes, draft jobs and notes, against a real migrated database."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from nursing_core.clock import FixedClock
from nursing_core.domain.errors import (
    AlreadyDrafted,
    DailyCapReached,
    Forbidden,
    IdempotencyConflict,
    NoteLocked,
    NotFound,
    NotRetryable,
    StaleVersion,
)
from nursing_core.domain.hashing import SignedNote, content_hash, signed_content
from nursing_core.domain.jobs import JobFailure, JobStatus
from nursing_core.domain.notes import Discard, Note, NoteStatus, RoughNote, Signature
from nursing_core.storage import notes as notes_module
from nursing_core.storage import tables
from nursing_core.storage.notes import JOB_LEASE, MAX_JOB_ATTEMPTS
from nursing_core.storage.repositories import PgNoteRepository
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from .world import NOW, World, add_patient, build_world, confirmed, draft_note, rough_note

CLOCK = FixedClock(datetime(2026, 11, 12, 9, 0, tzinfo=UTC))
HASH_A = "a" * 64
HASH_B = "b" * 64


async def _drafted(repo: PgNoteRepository, world: World) -> Note:
    """A rough note taken through a job to a stored draft note (version 1)."""
    rough = rough_note(world)
    _, job = await repo.add_rough_note(rough, str(uuid4()), HASH_A)
    assert await repo.claim_job(job.id) is not None
    note = draft_note(rough, world)
    await repo.complete_job(job.id, note)
    return note


async def _count(engine: AsyncEngine, table: object) -> int:
    async with engine.connect() as conn:
        return await conn.scalar(select(func.count()).select_from(table)) or 0  # type: ignore[arg-type]


def _signed(note: Note, rough: RoughNote, world: World) -> SignedNote:
    at = NOW + timedelta(minutes=5)
    content = signed_content(note, rough, world.nurse_id, at)
    return SignedNote(
        note_id=note.id,
        content=content,
        signature=Signature(
            signed_by=world.nurse_id, signed_at=at, content_hash=content_hash(content)
        ),
    )


@pytest.mark.asyncio
async def test_rough_note_round_trips_with_its_shift_and_a_queued_job(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    repo = PgNoteRepository(engine, CLOCK)
    rough = rough_note(world)

    stored, job = await repo.add_rough_note(rough, "key-1", HASH_A)

    again, again_job = await repo.add_rough_note(rough_note(world), "key-1", HASH_A)
    fetched = await repo.get_rough_note(rough.id)

    assert rough.written_at.utcoffset() != timedelta(0)  # the input is not in UTC
    for seen in (stored, again, fetched):
        assert seen == rough
        assert seen.written_at.utcoffset() == timedelta(0)
        assert seen.shift.starts_at.utcoffset() == timedelta(0)
        assert seen.shift.ends_at.utcoffset() == timedelta(0)
    assert again_job == job
    for instant in (job.created_at, job.updated_at):
        assert instant.utcoffset() == timedelta(0)
    assert (job.status, job.failure, job.note_id) == (JobStatus.QUEUED, None, None)
    assert job.rough_note_id == rough.id
    assert await repo.get_job(job.id) == job
    assert await repo.queued_job_ids() == [job.id]


@pytest.mark.asyncio
async def test_same_key_same_body_returns_existing(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    repo = PgNoteRepository(engine, CLOCK)
    first_note, first_job = await repo.add_rough_note(rough_note(world), "key-1", HASH_A)

    again_note, again_job = await repo.add_rough_note(rough_note(world), "key-1", HASH_A)

    assert (again_note, again_job) == (first_note, first_job)
    assert await _count(engine, tables.rough_note) == 1
    assert await _count(engine, tables.draft_job) == 1


@pytest.mark.asyncio
async def test_same_key_other_body_raises_idempotency_conflict(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    repo = PgNoteRepository(engine, CLOCK)
    await repo.add_rough_note(rough_note(world), "key-1", HASH_A)

    with pytest.raises(IdempotencyConflict):
        await repo.add_rough_note(rough_note(world), "key-1", HASH_B)

    assert await _count(engine, tables.rough_note) == 1


@pytest.mark.asyncio
async def test_two_identical_requests_racing_get_the_same_pair(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    repo = PgNoteRepository(engine, CLOCK)

    first, second = await asyncio.gather(
        repo.add_rough_note(rough_note(world), "key-1", HASH_A),
        repo.add_rough_note(rough_note(world), "key-1", HASH_A),
    )

    assert first == second
    assert await _count(engine, tables.rough_note) == 1
    assert await _count(engine, tables.draft_job) == 1


@pytest.mark.asyncio
async def test_a_key_is_scoped_to_its_author(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    repo = PgNoteRepository(engine, CLOCK)
    await repo.add_rough_note(rough_note(world), "key-1", HASH_A)

    await repo.add_rough_note(rough_note(world, author_id=world.admin_id), "key-1", HASH_B)

    assert await _count(engine, tables.rough_note) == 2


@pytest.mark.asyncio
async def test_missing_rows_are_not_found(engine: AsyncEngine) -> None:
    await build_world(engine)
    repo = PgNoteRepository(engine, CLOCK)
    for call in (
        repo.get_rough_note(uuid4()),
        repo.get_job(uuid4()),
        repo.get_note(uuid4()),
        repo.fail_job(uuid4(), JobFailure.PROVIDER_ERROR),
    ):
        with pytest.raises(NotFound):
            await call


@pytest.mark.asyncio
async def test_claim_job_only_once(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    repo = PgNoteRepository(engine, CLOCK)
    rough = rough_note(world)
    _, job = await repo.add_rough_note(rough, "key-1", HASH_A)

    claims = await asyncio.gather(*(repo.claim_job(job.id) for _ in range(5)))

    assert [c for c in claims if c is not None] == [rough]
    assert (await repo.get_job(job.id)).status is JobStatus.RUNNING
    assert await repo.queued_job_ids() == []
    assert await repo.claim_job(uuid4()) is None


@pytest.mark.asyncio
async def test_complete_job_stores_the_note_and_marks_the_job_succeeded(
    engine: AsyncEngine,
) -> None:
    world = await build_world(engine)
    repo = PgNoteRepository(engine, CLOCK)
    rough = rough_note(world)
    _, job = await repo.add_rough_note(rough, "key-1", HASH_A)
    await repo.claim_job(job.id)
    note = draft_note(rough, world)

    await repo.complete_job(job.id, note)

    assert await repo.get_note(note.id) == note
    done = await repo.get_job(job.id)
    assert (done.status, done.note_id) == (JobStatus.SUCCEEDED, note.id)


@pytest.mark.asyncio
async def test_complete_job_needs_a_running_job(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    repo = PgNoteRepository(engine, CLOCK)
    rough = rough_note(world)
    _, job = await repo.add_rough_note(rough, "key-1", HASH_A)

    with pytest.raises(NotFound):
        await repo.complete_job(job.id, draft_note(rough, world))

    assert await _count(engine, tables.note) == 0
    assert (await repo.get_job(job.id)).status is JobStatus.QUEUED


@pytest.mark.asyncio
async def test_fail_job_records_the_failure(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    repo = PgNoteRepository(engine, CLOCK)
    _, job = await repo.add_rough_note(rough_note(world), "key-1", HASH_A)
    await repo.claim_job(job.id)

    await repo.fail_job(job.id, JobFailure.REPLAY_MISSING)

    failed = await repo.get_job(job.id)
    assert (failed.status, failed.failure) == (JobStatus.FAILED, JobFailure.REPLAY_MISSING)


@pytest.mark.asyncio
async def test_fail_running_jobs_leaves_queued_ones_for_the_queue(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    repo = PgNoteRepository(engine, CLOCK)
    _, running = await repo.add_rough_note(rough_note(world), "key-1", HASH_A)
    _, queued = await repo.add_rough_note(rough_note(world), "key-2", HASH_A)
    await repo.claim_job(running.id)

    assert await repo.fail_running_jobs(JobFailure.PROVIDER_ERROR) == 1

    assert (await repo.get_job(running.id)).failure is JobFailure.PROVIDER_ERROR
    assert (await repo.get_job(queued.id)).status is JobStatus.QUEUED
    assert await repo.queued_job_ids() == [queued.id]


@pytest.mark.asyncio
async def test_queued_job_ids_come_oldest_first(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    ids: list[UUID] = []
    for n in range(3):
        repo = PgNoteRepository(engine, FixedClock(CLOCK.now() + timedelta(minutes=n)))
        _, job = await repo.add_rough_note(rough_note(world), f"key-{n}", HASH_A)
        ids.append(job.id)

    assert await PgNoteRepository(engine, CLOCK).queued_job_ids() == ids


@pytest.mark.asyncio
async def test_shift_rough_notes_and_entries_are_this_encounters_and_this_shifts(
    engine: AsyncEngine,
) -> None:
    world = await build_world(engine)
    repo = PgNoteRepository(engine, CLOCK)
    shift = world.case.rough_note.shift
    other_shift = shift.model_copy(
        update={
            "code": "6-2",
            "starts_at": shift.starts_at + timedelta(days=1),
            "ends_at": shift.ends_at + timedelta(days=1),
        }
    )
    _, other_encounter = await add_patient(
        engine,
        world,
        display_name="Demo patient Q",
        ward="Annex",
        bed_label="1",
        record_number="R-9",
    )
    t = shift.starts_at
    late = rough_note(world, written_at=t + timedelta(hours=3))
    early = rough_note(world, written_at=t + timedelta(hours=1))
    await repo.add_rough_note(late, "k1", HASH_A)
    _, early_job = await repo.add_rough_note(early, "k2", HASH_A)
    await repo.add_rough_note(rough_note(world, shift=other_shift), "k3", HASH_A)
    await repo.add_rough_note(rough_note(world, encounter_id=other_encounter), "k4", HASH_A)
    note = draft_note(early, world)
    await repo.claim_job(early_job.id)
    await repo.complete_job(early_job.id, note)

    assert await repo.shift_rough_notes(world.encounter_id, shift) == [early, late]
    entries = await repo.shift_entries(world.encounter_id, shift)
    assert [e.rough_note for e in entries] == [early, late]
    assert [e.note_status for e in entries] == [NoteStatus.DRAFT, None]
    assert [e.job.status for e in entries] == [JobStatus.SUCCEEDED, JobStatus.QUEUED]
    assert await repo.shift_rough_notes(world.encounter_id, other_shift) != []
    assert await repo.shift_entries(uuid4(), shift) == []


@pytest.mark.asyncio
async def test_save_draft_stores_and_bumps_the_version(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    repo = PgNoteRepository(engine, CLOCK)
    note = await _drafted(repo, world)
    changed = note.model_copy(update={"draft": confirmed(note.draft)})

    saved = await repo.save_draft(changed, 1)

    assert saved == changed.model_copy(update={"version": 2})
    assert await repo.get_note(note.id) == saved


@pytest.mark.asyncio
async def test_save_draft_with_stale_version_raises(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    repo = PgNoteRepository(engine, CLOCK)
    note = await _drafted(repo, world)
    changed = note.model_copy(update={"draft": confirmed(note.draft)})
    await repo.save_draft(changed, 1)

    with pytest.raises(StaleVersion):
        await repo.save_draft(note, 1)

    stored = await repo.get_note(note.id)
    assert stored.version == 2
    assert stored.draft == changed.draft


@pytest.mark.asyncio
async def test_save_draft_of_a_missing_note_is_not_found(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    note = draft_note(rough_note(world), world)
    with pytest.raises(NotFound):
        await PgNoteRepository(engine, CLOCK).save_draft(note, 1)


@pytest.mark.asyncio
async def test_only_sign_writes_a_record(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    repo = PgNoteRepository(engine, CLOCK)
    note = await _drafted(repo, world)
    other = await _drafted(repo, world)
    changed = note.model_copy(update={"draft": confirmed(note.draft)})

    saved = await repo.save_draft(changed, 1)
    await repo.discard(other.id, 1, Discard(discarded_by=world.nurse_id, discarded_at=NOW))
    assert await _count(engine, tables.note_version) == 0

    rough = await repo.get_rough_note(note.rough_note_id)
    record = _signed(saved, rough, world)
    signed = await repo.sign(note.id, 2, record)

    assert (signed.status, signed.version, signed.signature) == (
        NoteStatus.SIGNED,
        3,
        record.signature,
    )
    assert await repo.get_note(note.id) == signed
    async with engine.connect() as conn:
        row = (await conn.execute(select(tables.note_version))).one()
    assert (row.note_id, row.version, row.content_hash) == (
        note.id,
        3,
        record.signature.content_hash,
    )
    assert (row.signed_by, row.signed_at) == (world.nurse_id, record.signature.signed_at)
    assert row.content == record.content.model_dump(mode="json")


@pytest.mark.asyncio
async def test_signing_a_stale_version_writes_nothing(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    repo = PgNoteRepository(engine, CLOCK)
    note = await _drafted(repo, world)
    changed = note.model_copy(update={"draft": confirmed(note.draft)})
    saved = await repo.save_draft(changed, 1)
    record = _signed(saved, await repo.get_rough_note(note.rough_note_id), world)

    with pytest.raises(StaleVersion):
        await repo.sign(note.id, 1, record)

    assert (await repo.get_note(note.id)).status is NoteStatus.DRAFT
    assert await _count(engine, tables.note_version) == 0


@pytest.mark.asyncio
async def test_a_locked_note_refuses_every_change_before_its_version_is_checked(
    engine: AsyncEngine,
) -> None:
    world = await build_world(engine)
    repo = PgNoteRepository(engine, CLOCK)
    note = await _drafted(repo, world)
    saved = await repo.save_draft(note.model_copy(update={"draft": confirmed(note.draft)}), 1)
    record = _signed(saved, await repo.get_rough_note(note.rough_note_id), world)
    signed = await repo.sign(note.id, 2, record)
    discard = Discard(discarded_by=world.nurse_id, discarded_at=NOW)

    with pytest.raises(NoteLocked):
        await repo.save_draft(signed, 1)  # a stale version too: the lock is reported first
    with pytest.raises(NoteLocked):
        await repo.sign(note.id, 3, record)
    with pytest.raises(NoteLocked):
        await repo.discard(note.id, 99, discard)

    assert await repo.get_note(note.id) == signed
    assert await _count(engine, tables.note_version) == 1


@pytest.mark.asyncio
async def test_discard_bumps_the_version_and_locks_the_note(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    repo = PgNoteRepository(engine, CLOCK)
    note = await _drafted(repo, world)
    discard = Discard(discarded_by=world.nurse_id, discarded_at=NOW)

    with pytest.raises(StaleVersion):
        await repo.discard(note.id, 5, discard)
    discarded = await repo.discard(note.id, 1, discard)

    assert (discarded.status, discarded.version, discarded.discard) == (
        NoteStatus.DISCARDED,
        2,
        discard,
    )
    with pytest.raises(NoteLocked):
        await repo.save_draft(note, 2)
    with pytest.raises(NotFound):
        await repo.discard(uuid4(), 1, discard)


@pytest.mark.asyncio
async def test_signing_with_another_notes_record_is_refused(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    repo = PgNoteRepository(engine, CLOCK)
    note = await _drafted(repo, world)
    other = await _drafted(repo, world)
    other_saved = await repo.save_draft(
        other.model_copy(update={"draft": confirmed(other.draft)}), 1
    )
    record = _signed(other_saved, await repo.get_rough_note(other.rough_note_id), world)

    with pytest.raises(ValueError, match="record"):
        await repo.sign(note.id, 1, record)

    assert (await repo.get_note(note.id)).status is NoteStatus.DRAFT


class _MovingClock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def now(self) -> datetime:
        return self.at


async def _job_row(engine: AsyncEngine, job_id: UUID) -> tuple[str, str | None, int]:
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                select(
                    tables.draft_job.c.status,
                    tables.draft_job.c.failure,
                    tables.draft_job.c.attempts,
                ).where(tables.draft_job.c.id == job_id)
            )
        ).one()
    return row.status, row.failure, row.attempts


@pytest.mark.asyncio
async def test_a_claim_is_a_lease_that_expires_after_150_seconds(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    clock = _MovingClock(CLOCK.now())
    repo = PgNoteRepository(engine, clock)
    rough = rough_note(world)
    _, job = await repo.add_rough_note(rough, "key-1", HASH_A)

    assert await repo.claim_job(job.id) == rough
    assert await _job_row(engine, job.id) == ("running", None, 1)

    clock.at += JOB_LEASE - timedelta(seconds=1)
    assert await repo.claim_job(job.id) is None  # inside the lease
    assert await _job_row(engine, job.id) == ("running", None, 1)

    clock.at += timedelta(seconds=2)
    assert await repo.claim_job(job.id) == rough  # the lease ran out
    assert await _job_row(engine, job.id) == ("running", None, 2)


@pytest.mark.asyncio
async def test_the_fourth_claim_fails_the_job_instead_of_running_it(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    clock = _MovingClock(CLOCK.now())
    repo = PgNoteRepository(engine, clock)
    _, job = await repo.add_rough_note(rough_note(world), "key-1", HASH_A)

    for _ in range(MAX_JOB_ATTEMPTS):
        assert await repo.claim_job(job.id) is not None
        clock.at += JOB_LEASE + timedelta(seconds=1)

    assert await repo.claim_job(job.id) is None
    status, failure, _ = await _job_row(engine, job.id)
    assert (status, failure) == ("failed", "provider_error")
    assert await repo.claim_job(job.id) is None  # a failed job stays failed


@pytest.mark.asyncio
async def test_a_succeeded_job_is_never_claimed_again(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    clock = _MovingClock(CLOCK.now())
    repo = PgNoteRepository(engine, clock)
    note = await _drafted(repo, world)
    del note
    clock.at += JOB_LEASE * 10
    async with engine.connect() as conn:
        job = (await conn.execute(select(tables.draft_job.c.id))).scalars().first()
    assert job is not None
    assert await repo.claim_job(job) is None


async def _invited_user(engine: AsyncEngine, world: World) -> UUID:
    """A non-persona user (an invited nurse) with the demo nurse's role and facility."""
    user_id = uuid4()
    async with engine.begin() as conn:
        nurse = (
            await conn.execute(
                select(tables.app_user).where(tables.app_user.c.id == world.nurse_id)
            )
        ).one()
        await conn.execute(
            tables.app_user.insert().values(
                id=user_id,
                display_name="Invited Nurse",
                initials="IN",
                role=nurse.role,
                facility_id=nurse.facility_id,
                email=f"invited-{user_id}@example.com",
                persona=False,
            )
        )
    return user_id


@pytest.mark.asyncio
async def test_written_by_persona_reads_the_notes_author(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    repo = PgNoteRepository(engine, CLOCK)
    invited = await _invited_user(engine, world)
    by_persona = rough_note(world)
    by_invited = rough_note(world, author_id=invited)
    await repo.add_rough_note(by_persona, "k1", HASH_A)
    await repo.add_rough_note(by_invited, "k1", HASH_B)

    assert await repo.written_by_persona(by_persona.id) is True
    assert await repo.written_by_persona(by_invited.id) is False
    with pytest.raises(NotFound):
        await repo.written_by_persona(uuid4())


@pytest.mark.asyncio
async def test_jobs_since_counts_one_authors_jobs_created_after_the_cutoff(
    engine: AsyncEngine,
) -> None:
    world = await build_world(engine)
    invited = await _invited_user(engine, world)
    early = PgNoteRepository(engine, FixedClock(NOW - timedelta(hours=30)))
    late = PgNoteRepository(engine, FixedClock(NOW - timedelta(hours=2)))
    await early.add_rough_note(rough_note(world, author_id=invited), "old", HASH_A)
    await late.add_rough_note(rough_note(world, author_id=invited), "new-1", HASH_A)
    await late.add_rough_note(rough_note(world, author_id=invited), "new-2", HASH_B)
    await late.add_rough_note(rough_note(world), "someone-else", HASH_A)

    assert await late.jobs_since(invited, NOW - timedelta(hours=24)) == 2
    assert await late.jobs_since(invited, NOW - timedelta(hours=1)) == 0
    assert await late.jobs_since(world.nurse_id, NOW - timedelta(hours=24)) == 1


# A retry is made later than the job it follows: the newest job is the one created last.
LATER = CLOCK.now() + timedelta(minutes=5)


async def _failed(repo: PgNoteRepository, world: World, failure: JobFailure, **changes: object):
    rough = rough_note(world, **changes)
    _, job = await repo.add_rough_note(rough, str(uuid4()), HASH_A)
    await repo.fail_job(job.id, failure)
    return rough, job


@pytest.mark.asyncio
async def test_redraft_after_a_retryable_failure_makes_a_new_job_and_keeps_the_old_one(
    engine: AsyncEngine,
) -> None:
    world = await build_world(engine)
    repo = PgNoteRepository(engine, CLOCK)
    rough, failed = await _failed(repo, world, JobFailure.PROVIDER_ERROR)

    job, is_new = await repo.redraft(rough.id, world.nurse_id, LATER)

    assert is_new is True
    assert job.id != failed.id
    assert (job.status, job.rough_note_id) == (JobStatus.QUEUED, rough.id)
    assert (await repo.get_job(failed.id)).status is JobStatus.FAILED
    assert await _count(engine, tables.draft_job) == 2


@pytest.mark.asyncio
async def test_redraft_returns_the_open_job_as_it_is(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    repo = PgNoteRepository(engine, CLOCK)
    rough = rough_note(world)
    _, queued = await repo.add_rough_note(rough, "k", HASH_A)

    assert await repo.redraft(rough.id, world.nurse_id, LATER) == (queued, False)
    await repo.claim_job(queued.id)
    job, is_new = await repo.redraft(rough.id, world.nurse_id, LATER)
    assert (job.id, job.status, is_new) == (queued.id, JobStatus.RUNNING, False)


@pytest.mark.asyncio
async def test_redraft_refuses_a_succeeded_job_and_a_failure_a_retry_would_repeat(
    engine: AsyncEngine,
) -> None:
    world = await build_world(engine)
    repo = PgNoteRepository(engine, CLOCK)
    drafted = await _drafted(repo, world)
    with pytest.raises(AlreadyDrafted):
        await repo.redraft(drafted.rough_note_id, world.nurse_id, LATER)
    for failure in (
        JobFailure.MODEL_REFUSED,
        JobFailure.REPLAY_MISSING,
        JobFailure.AI_BUDGET_REACHED,
    ):
        rough, _ = await _failed(repo, world, failure)
        with pytest.raises(NotRetryable):
            await repo.redraft(rough.id, world.nurse_id, LATER)


@pytest.mark.asyncio
async def test_redraft_knows_the_note_and_its_author(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    repo = PgNoteRepository(engine, CLOCK)
    rough, _ = await _failed(repo, world, JobFailure.PROVIDER_ERROR)
    with pytest.raises(NotFound):
        await repo.redraft(uuid4(), world.nurse_id, LATER)
    with pytest.raises(Forbidden):
        await repo.redraft(rough.id, await _invited_user(engine, world), LATER)
    assert await _count(engine, tables.draft_job) == 1


@pytest.mark.asyncio
async def test_two_redrafts_at_once_make_one_job(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await build_world(engine)
    repo = PgNoteRepository(engine, CLOCK)
    rough, _ = await _failed(repo, world, JobFailure.INVALID_OUTPUT)
    # Pause after reading the newest job, so that without the rough note's row lock every tap
    # would read the failed job before any had inserted (and the losers would hit the unique index).
    newest = notes_module._newest_job  # pyright: ignore[reportPrivateUsage]

    async def slow_newest(*args: Any) -> Any:
        row = await newest(*args)
        await asyncio.sleep(0.2)
        return row

    monkeypatch.setattr(notes_module, "_newest_job", slow_newest)

    results = await asyncio.gather(
        *(repo.redraft(rough.id, world.nurse_id, LATER) for _ in range(4))
    )

    assert sorted(is_new for _, is_new in results) == [False, False, False, True]
    assert len({job.id for job, _ in results}) == 1
    assert await _count(engine, tables.draft_job) == 2


@pytest.mark.asyncio
async def test_redraft_counts_toward_the_daily_cap_only_when_it_makes_a_job(
    engine: AsyncEngine,
) -> None:
    world = await build_world(engine)
    repo = PgNoteRepository(engine, CLOCK)
    invited = await _invited_user(engine, world)
    rough = rough_note(world, author_id=invited)
    _, job = await repo.add_rough_note(rough, "k", HASH_A, daily_cap=2)
    await repo.fail_job(job.id, JobFailure.PROVIDER_ERROR)

    second, is_new = await repo.redraft(rough.id, invited, LATER, daily_cap=2)
    assert is_new
    # At the cap now: the open job still comes back, a new one would not.
    assert await repo.redraft(rough.id, invited, LATER, daily_cap=2) == (second, False)
    await repo.fail_job(second.id, JobFailure.PROVIDER_ERROR)
    with pytest.raises(DailyCapReached):
        await repo.redraft(rough.id, invited, LATER, daily_cap=2)
    assert await _count(engine, tables.draft_job) == 2


@pytest.mark.asyncio
async def test_add_rough_note_at_the_cap_raises_and_saves_nothing_but_a_replay_is_answered(
    engine: AsyncEngine,
) -> None:
    world = await build_world(engine)
    repo = PgNoteRepository(engine, CLOCK)
    invited = await _invited_user(engine, world)
    first = rough_note(world, author_id=invited)
    stored, job = await repo.add_rough_note(first, "k1", HASH_A, daily_cap=1)

    with pytest.raises(DailyCapReached):
        await repo.add_rough_note(rough_note(world, author_id=invited), "k2", HASH_B, daily_cap=1)
    assert await _count(engine, tables.rough_note) == 1
    assert await repo.add_rough_note(
        rough_note(world, author_id=invited), "k1", HASH_A, daily_cap=1
    ) == (
        stored,
        job,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("attempt", range(5))
async def test_two_new_keys_at_once_one_below_the_cap_make_exactly_one_job(
    engine: AsyncEngine, attempt: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await build_world(engine)
    repo = PgNoteRepository(engine, CLOCK)
    invited = await _invited_user(engine, world)
    cap = 3
    for number in range(cap - 1):
        await repo.add_rough_note(
            rough_note(world, author_id=invited), f"used-{attempt}-{number}", HASH_A, daily_cap=cap
        )

    # Pause between the count and the insert, so that without the author's lock both requests
    # would count before either had inserted.
    count = notes_module._check_cap  # pyright: ignore[reportPrivateUsage]

    async def slow_count(*args: Any) -> None:
        await count(*args)
        await asyncio.sleep(0.2)

    monkeypatch.setattr(notes_module, "_check_cap", slow_count)
    outcomes = await asyncio.gather(
        *(
            repo.add_rough_note(
                rough_note(world, author_id=invited), f"race-{attempt}-{n}", HASH_B, daily_cap=cap
            )
            for n in range(2)
        ),
        return_exceptions=True,
    )

    assert sum(isinstance(o, DailyCapReached) for o in outcomes) == 1
    assert sum(isinstance(o, tuple) for o in outcomes) == 1
    assert await repo.jobs_since(invited, NOW - timedelta(days=2)) == cap


@pytest.mark.asyncio
async def test_a_replayed_key_returns_the_newest_job_after_a_retry(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    repo = PgNoteRepository(engine, CLOCK)
    rough = rough_note(world)
    _, first = await repo.add_rough_note(rough, "k", HASH_A)
    await repo.fail_job(first.id, JobFailure.PROVIDER_ERROR)
    retry, _ = await repo.redraft(rough.id, world.nurse_id, LATER)

    _, replayed = await repo.add_rough_note(rough_note(world), "k", HASH_A)

    assert replayed.id == retry.id


@pytest.mark.asyncio
async def test_shift_entries_show_the_newest_job(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    repo = PgNoteRepository(engine, CLOCK)
    rough = rough_note(world)
    _, first = await repo.add_rough_note(rough, "k", HASH_A)
    await repo.fail_job(first.id, JobFailure.PROVIDER_ERROR)
    retry, _ = await repo.redraft(rough.id, world.nurse_id, LATER)

    entries = await repo.shift_entries(rough.encounter_id, rough.shift)

    assert [entry.job.id for entry in entries] == [retry.id]


SECOND = timedelta(seconds=1)
MINUTE = timedelta(seconds=60)


async def _queued_at(engine: AsyncEngine, world: World, key: str = "key-1") -> UUID:
    _, job = await PgNoteRepository(engine, CLOCK).add_rough_note(rough_note(world), key, HASH_A)
    return job.id


def _repo_at(engine: AsyncEngine, later: timedelta) -> PgNoteRepository:
    return PgNoteRepository(engine, FixedClock(CLOCK.now() + later))


@pytest.mark.asyncio
async def test_a_queued_job_is_re_sent_once_a_minute(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    job_id = await _queued_at(engine, world)

    assert await _repo_at(engine, 59 * SECOND).resend_due([job_id]) == []  # just sent
    assert await _repo_at(engine, 61 * SECOND).resend_due([job_id]) == [job_id]
    assert await _repo_at(engine, 62 * SECOND).resend_due([job_id]) == []  # sent a second ago
    assert await _repo_at(engine, 120 * SECOND).resend_due([job_id]) == []  # 59 s after the send
    assert await _repo_at(engine, 122 * SECOND).resend_due([job_id]) == [job_id]


@pytest.mark.asyncio
async def test_two_polls_at_once_re_send_a_stuck_job_once(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    job_id = await _queued_at(engine, world)
    repo = _repo_at(engine, 90 * SECOND)

    answers = await asyncio.gather(*(repo.resend_due([job_id]) for _ in range(6)))

    assert sorted(len(a) for a in answers) == [0, 0, 0, 0, 0, 1]


@pytest.mark.asyncio
async def test_a_running_job_is_re_sent_only_after_its_lease_ran_out(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    job_id = await _queued_at(engine, world)
    assert await PgNoteRepository(engine, CLOCK).claim_job(job_id) is not None

    assert await _repo_at(engine, JOB_LEASE - SECOND).resend_due([job_id]) == []
    assert await _repo_at(engine, JOB_LEASE + SECOND).resend_due([job_id]) == [job_id]
    # The send is counted: the lease is still over, but the last send is a second old.
    assert await _repo_at(engine, JOB_LEASE + 2 * SECOND).resend_due([job_id]) == []


@pytest.mark.asyncio
async def test_finished_jobs_and_other_ids_are_never_re_sent(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    repo = PgNoteRepository(engine, CLOCK)
    rough = rough_note(world)
    _, done = await repo.add_rough_note(rough, "key-done", HASH_A)
    await repo.claim_job(done.id)
    await repo.complete_job(done.id, draft_note(rough, world))
    _, failed = await repo.add_rough_note(rough_note(world), "key-failed", HASH_A)
    await repo.claim_job(failed.id)
    await repo.fail_job(failed.id, JobFailure.PROVIDER_ERROR)
    late = _repo_at(engine, 10 * MINUTE)

    assert await late.resend_due([done.id, failed.id, uuid4()]) == []
    assert await late.resend_due([]) == []


@pytest.mark.asyncio
async def test_shift_rough_notes_keep_to_one_side_when_asked(engine: AsyncEngine) -> None:
    # A draft's missing-items checklist reads the shift's other rough notes: a persona's note
    # must never count for an invited nurse's draft, nor the reverse.
    world = await build_world(engine)
    repo = PgNoteRepository(engine, CLOCK)
    invited = await _invited_user(engine, world)
    by_persona = rough_note(world)
    by_invited = rough_note(world, author_id=invited)
    await repo.add_rough_note(by_persona, "k1", HASH_A)
    await repo.add_rough_note(by_invited, "k1", HASH_B)
    shift = world.case.rough_note.shift

    assert await repo.shift_rough_notes(world.encounter_id, shift, persona=True) == [by_persona]
    assert await repo.shift_rough_notes(world.encounter_id, shift, persona=False) == [by_invited]
    assert len(await repo.shift_rough_notes(world.encounter_id, shift)) == 2
