"""Sessions, users and AI usage against a real migrated database, and the typed port checks."""

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from nursing_core.clock import FixedClock
from nursing_core.domain.errors import NotFound
from nursing_core.domain.users import Role
from nursing_core.ports import FacilityRepository, NoteRepository, PatientRepository
from nursing_core.storage import tables
from nursing_core.storage.repositories import (
    SESSION_LIFETIME,
    MonthUsage,
    PgFacilityRepository,
    PgNoteRepository,
    PgPatientRepository,
    PgSessionRepository,
    PgUsageRepository,
    PgUserRepository,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from .world import NOW, build_world, generation, rough_note

CLOCK = FixedClock(NOW)


def test_the_repositories_satisfy_their_ports(engine: AsyncEngine) -> None:
    facilities: FacilityRepository = PgFacilityRepository(engine, CLOCK)
    patients: PatientRepository = PgPatientRepository(engine, CLOCK)
    notes: NoteRepository = PgNoteRepository(engine, CLOCK)
    assert (facilities, patients, notes) != ()


@pytest.mark.asyncio
async def test_get_user_returns_the_role_and_facility_key(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    repo = PgUserRepository(engine)

    nurse = await repo.get_user(world.nurse_id)
    admin = await repo.get_user(world.admin_id)

    assert (nurse.id, nurse.role, nurse.facility_key) == (
        world.nurse_id,
        Role.STAFF_NURSE,
        world.profile.key,
    )
    assert nurse.initials
    assert nurse.display_name
    assert (admin.role, admin.facility_key) == (Role.ADMIN, None)
    with pytest.raises(NotFound):
        await repo.get_user(uuid4())


@pytest.mark.asyncio
async def test_session_stores_only_a_hash_and_expires_after_twelve_hours(
    engine: AsyncEngine,
) -> None:
    world = await build_world(engine)
    repo = PgSessionRepository(engine)
    shift = world.case.rough_note.shift

    token = await repo.create(world.nurse_id, shift, NOW)

    async with engine.connect() as conn:
        stored = (await conn.execute(select(tables.session.c.token_hash))).scalars().all()
    assert stored == [hashlib.sha256(token.encode()).hexdigest()]
    assert token not in stored
    session = await repo.get(token, NOW + timedelta(hours=1))
    assert session is not None
    assert (session.user_id, session.shift) == (world.nurse_id, shift)
    assert session.expires_at == NOW + SESSION_LIFETIME == NOW + timedelta(hours=12)
    assert await repo.get(token, NOW + timedelta(hours=12) - timedelta(seconds=1)) is not None
    assert await repo.get(token, NOW + timedelta(hours=12)) is None
    assert await repo.get("not-a-token", NOW) is None


@pytest.mark.asyncio
async def test_tokens_are_random_and_an_admin_session_has_no_shift(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    repo = PgSessionRepository(engine)

    first = await repo.create(world.admin_id, None, NOW)
    second = await repo.create(world.admin_id, None, NOW)

    assert first != second
    assert len(first) >= 43
    session = await repo.get(first, NOW)
    assert session is not None
    assert session.shift is None


@pytest.mark.asyncio
async def test_set_shift_and_delete(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    repo = PgSessionRepository(engine)
    shift = world.case.rough_note.shift
    later = shift.model_copy(
        update={
            "code": "6-2",
            "starts_at": shift.starts_at + timedelta(hours=8),
            "ends_at": shift.ends_at + timedelta(hours=8),
        }
    )
    token = await repo.create(world.nurse_id, shift, NOW)

    await repo.set_shift(token, later)
    session = await repo.get(token, NOW)
    assert session is not None
    assert session.shift == later
    assert session.expires_at == NOW + SESSION_LIFETIME

    await repo.delete(token)
    assert await repo.get(token, NOW) is None
    await repo.delete(token)  # no session: nothing to do


@pytest.mark.asyncio
async def test_usage_month_total_covers_the_utc_calendar_month(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    repo = PgUsageRepository(engine)
    assert await repo.month_total(NOW) == (Decimal(0), 0)
    rough_repo = PgNoteRepository(engine, CLOCK)
    _, job = await rough_repo.add_rough_note(rough_note(world), "k", "a" * 64)
    info = generation()
    at = datetime(2026, 11, 3, tzinfo=UTC)
    await repo.record(job.id, info, at)
    await repo.record(None, info, datetime(2026, 11, 30, 23, 59, 59, tzinfo=UTC))
    await repo.record(None, info, datetime(2026, 10, 31, 23, 59, 59, tzinfo=UTC))
    await repo.record(None, info, datetime(2026, 12, 1, tzinfo=UTC))

    total, calls = await repo.month_total(datetime(2026, 11, 15, 12, tzinfo=UTC))

    assert (total, calls) == (info.cost_usd * 2, 2)
    assert await repo.month_total(datetime(2026, 12, 20, tzinfo=UTC)) == (info.cost_usd, 1)
    # Only the live model's answers are billed: a mock or replay answer is recorded at $0.
    billed = info.model_copy(update={"provider": "anthropic"})
    await repo.record(None, billed, at)
    assert await repo.month_usage(datetime(2026, 11, 15, 12, tzinfo=UTC)) == MonthUsage(
        cost_usd=info.cost_usd * 3, calls=3, billed_calls=1
    )
    assert await repo.month_usage(datetime(2026, 9, 1, tzinfo=UTC)) == MonthUsage(
        cost_usd=Decimal(0), calls=0, billed_calls=0
    )
    async with engine.connect() as conn:
        row = (
            await conn.execute(select(tables.ai_usage).where(tables.ai_usage.c.job_id == job.id))
        ).one()
    assert (row.provider, row.model, row.prompt_version) == (
        info.provider,
        info.model,
        info.prompt_version,
    )
    assert (row.input_tokens, row.output_tokens, row.created_at) == (120, 80, at)
