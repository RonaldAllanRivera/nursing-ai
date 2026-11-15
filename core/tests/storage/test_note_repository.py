"""The note repository: rough notes, draft jobs and notes, against a real migrated database."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from nursing_core.clock import FixedClock
from nursing_core.domain.errors import IdempotencyConflict, NoteLocked, NotFound, StaleVersion
from nursing_core.domain.hashing import SignedNote, content_hash, signed_content
from nursing_core.domain.jobs import JobFailure, JobStatus
from nursing_core.domain.notes import Discard, Note, NoteStatus, RoughNote, Signature
from nursing_core.storage import tables
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

    assert stored == rough
    assert await repo.get_rough_note(rough.id) == rough
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
