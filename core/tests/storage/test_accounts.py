"""Users and sessions against a real migrated database, and the typed port checks."""

import hashlib
from datetime import timedelta
from uuid import uuid4

import pytest
from nursing_core.clock import FixedClock
from nursing_core.domain.errors import NotFound
from nursing_core.domain.users import Role
from nursing_core.ports import FacilityRepository, NoteRepository, PatientRepository
from nursing_core.storage import tables
from nursing_core.storage.repositories import (
    SESSION_LIFETIME,
    PgFacilityRepository,
    PgNoteRepository,
    PgPatientRepository,
    PgSessionRepository,
    PgUserRepository,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from .world import NOW, build_world

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
async def test_each_session_gets_its_own_csrf_token_never_in_a_repr(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    repo = PgSessionRepository(engine)

    first = await repo.create(world.admin_id, None, NOW)
    second = await repo.create(world.admin_id, None, NOW)

    one, two = await repo.get(first, NOW), await repo.get(second, NOW)
    assert one is not None
    assert two is not None
    assert one.csrf_token != two.csrf_token
    assert len(one.csrf_token) >= 43
    assert one.csrf_token not in (first, second)
    assert one.csrf_token not in repr(one)
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                select(
                    tables.session.c.last_active_at,
                    tables.session.c.pin_verified_at,
                    tables.session.c.pin_failures,
                ).where(tables.session.c.token_hash == hashlib.sha256(first.encode()).hexdigest())
            )
        ).one()
    assert tuple(row) == (NOW, None, 0)


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
