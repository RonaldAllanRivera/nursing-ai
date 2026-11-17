"""Users and sessions against a real migrated database, and the typed port checks."""

import hashlib
from datetime import timedelta
from uuid import uuid4

import pytest
from nursing_core.auth.pins import MAX_PIN_TRIES, hash_pin, verify_pin
from nursing_core.clock import FixedClock
from nursing_core.demo import DEMO_PERSONAS, DEMO_PIN
from nursing_core.domain.errors import EmailTaken, IdentityMismatch, NotFound
from nursing_core.domain.users import Role, UserStatus
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
from nursing_core.storage.seed import seed
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

    token = (await repo.create(world.nurse_id, shift, NOW, 12)).token

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

    first = (await repo.create(world.admin_id, None, NOW, 12)).token
    second = (await repo.create(world.admin_id, None, NOW, 12)).token

    assert first != second
    assert len(first) >= 43
    session = await repo.get(first, NOW)
    assert session is not None
    assert session.shift is None


@pytest.mark.asyncio
async def test_each_session_gets_its_own_csrf_token_never_in_a_repr(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    repo = PgSessionRepository(engine)

    first = (await repo.create(world.admin_id, None, NOW, 12)).token
    second = (await repo.create(world.admin_id, None, NOW, 12)).token

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
    token = (await repo.create(world.nurse_id, shift, NOW, 12)).token

    await repo.set_shift(token, later)
    session = await repo.get(token, NOW)
    assert session is not None
    assert session.shift == later
    assert session.expires_at == NOW + SESSION_LIFETIME

    await repo.delete(token)
    assert await repo.get(token, NOW) is None
    await repo.delete(token)  # no session: nothing to do


ADMIN_EMAIL = "boss@example.com"
NURSE_EMAIL = "nina@example.com"


@pytest.mark.asyncio
async def test_invite_reads_invited_and_bind_google_makes_it_active(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    users = PgUserRepository(engine)
    admin = await users.invite(ADMIN_EMAIL, Role.ADMIN, None, None)

    invited = await users.invite(NURSE_EMAIL, Role.STAFF_NURSE, world.profile.key, admin.id)

    assert (invited.status, invited.has_pin, invited.pin_locked, invited.persona) == (
        UserStatus.INVITED,
        False,
        False,
        False,
    )
    assert (invited.email, invited.display_name) == (NURSE_EMAIL, NURSE_EMAIL)
    assert invited.initials == "N"
    assert invited.facility_key == world.profile.key
    bound = await users.bind_google(invited.id, "sub-1", "Nina Nurse", "NN")
    assert (bound.status, bound.display_name, bound.initials) == (
        UserStatus.ACTIVE,
        "Nina Nurse",
        "NN",
    )
    again = await users.bind_google(invited.id, "sub-1", "Other Name", "ON")
    assert again.display_name == "Nina Nurse"
    persona = await users.get_user(world.nurse_id)
    assert persona.status is UserStatus.ACTIVE
    assert persona.email is None


@pytest.mark.asyncio
async def test_email_lookup_is_case_insensitive(engine: AsyncEngine) -> None:
    users = PgUserRepository(engine)
    invited = await users.invite("Mixed.Case@Example.com", Role.ADMIN, None, None)

    found = await users.get_user_by_email("  MIXED.case@example.COM")

    assert found is not None
    assert found.id == invited.id
    assert found.email == "mixed.case@example.com"
    assert await users.get_user_by_email("nobody@example.com") is None


@pytest.mark.asyncio
async def test_bind_google_refuses_a_second_sub(engine: AsyncEngine) -> None:
    users = PgUserRepository(engine)
    first = await users.invite("one@example.com", Role.ADMIN, None, None)
    second = await users.invite("two@example.com", Role.ADMIN, None, None)
    await users.bind_google(first.id, "sub-a", "One", "O")

    with pytest.raises(IdentityMismatch):
        await users.bind_google(first.id, "sub-b", "One", "O")
    with pytest.raises(IdentityMismatch):  # a sub belongs to one person
        await users.bind_google(second.id, "sub-a", "Two", "T")
    assert (await users.get_user(second.id)).status is UserStatus.INVITED


@pytest.mark.asyncio
async def test_invite_twice_is_email_taken(engine: AsyncEngine) -> None:
    users = PgUserRepository(engine)
    await users.invite("dup@example.com", Role.ADMIN, None, None)

    with pytest.raises(EmailTaken):
        await users.invite("DUP@example.com", Role.ADMIN, None, None)


@pytest.mark.asyncio
async def test_invite_to_an_unknown_facility_is_not_found(engine: AsyncEngine) -> None:
    with pytest.raises(NotFound):
        await PgUserRepository(engine).invite("x@example.com", Role.STAFF_NURSE, "nowhere", None)


@pytest.mark.asyncio
async def test_revoke_ends_the_users_sessions(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    users, sessions = PgUserRepository(engine), PgSessionRepository(engine)
    invited = await users.invite(NURSE_EMAIL, Role.STAFF_NURSE, world.profile.key, None)
    mine = await sessions.create(invited.id, None, NOW, 12)
    other = await sessions.create(world.nurse_id, None, NOW, 12)

    revoked = await users.revoke(invited.id, NOW)

    assert revoked.status is UserStatus.REVOKED
    assert await sessions.get(mine.token, NOW) is None
    assert await sessions.get(other.token, NOW) is not None
    assert await users.revoke(invited.id, NOW + timedelta(hours=1)) == revoked
    async with engine.connect() as conn:
        at = (
            await conn.execute(
                select(tables.app_user.c.revoked_at).where(tables.app_user.c.id == invited.id)
            )
        ).scalar_one()
    assert at == NOW
    with pytest.raises(NotFound):
        await users.revoke(uuid4(), NOW)


@pytest.mark.asyncio
async def test_list_staff_skips_personas_and_orders_by_email(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    users = PgUserRepository(engine)
    await users.invite("zed@example.com", Role.STAFF_NURSE, world.profile.key, None)
    await users.invite("amy@example.com", Role.HEAD_NURSE, world.profile.key, None)
    await users.invite("root@example.com", Role.ADMIN, None, None)

    everyone = await users.list_staff(None)
    here = await users.list_staff(world.profile.key)

    assert [u.email for u in everyone] == [
        "amy@example.com",
        "root@example.com",
        "zed@example.com",
    ]
    assert [u.email for u in here] == ["amy@example.com", "zed@example.com"]
    assert await users.list_staff("nowhere") == []


@pytest.mark.asyncio
async def test_bootstrap_admin_only_while_no_active_admin(engine: AsyncEngine) -> None:
    world = await build_world(engine)  # its admin is a demo persona: it does not count
    users = PgUserRepository(engine)

    first = await users.ensure_bootstrap_admin("Root@Example.com")
    assert first is not None
    assert (first.role, first.facility_key, first.status) == (
        Role.ADMIN,
        None,
        UserStatus.INVITED,
    )
    again = await users.ensure_bootstrap_admin("root@example.com")
    assert again is not None
    assert again.id == first.id  # still waiting for its first sign-in
    # A nurse's email is never promoted.
    nurse = await users.invite(NURSE_EMAIL, Role.STAFF_NURSE, world.profile.key, None)
    assert await users.ensure_bootstrap_admin(NURSE_EMAIL) is None
    assert (await users.get_user(nurse.id)).role is Role.STAFF_NURSE
    # Once a Google admin is active, nobody else is made one.
    await users.bind_google(first.id, "sub-root", "Root", "R")
    assert await users.ensure_bootstrap_admin("other@example.com") is None
    assert await users.get_user_by_email("other@example.com") is None
    # A revoked admin is not revived, and no longer counts as active.
    await users.revoke(first.id, NOW)
    assert await users.ensure_bootstrap_admin("root@example.com") is None
    made = await users.ensure_bootstrap_admin("next@example.com")
    assert made is not None
    assert made.role is Role.ADMIN


@pytest.mark.asyncio
async def test_fifth_wrong_pin_locks_the_account(engine: AsyncEngine) -> None:
    users = PgUserRepository(engine)
    user = await users.invite(NURSE_EMAIL, Role.ADMIN, None, None)
    await users.set_pin(user.id, hash_pin("246813"))
    assert (await users.get_user(user.id)).has_pin

    left = [await users.record_pin_failure(user.id, NOW) for _ in range(MAX_PIN_TRIES - 1)]

    assert left == [4, 3, 2, 1]
    assert not (await users.get_user(user.id)).pin_locked
    assert await users.record_pin_failure(user.id, NOW) == 0
    assert (await users.get_user(user.id)).pin_locked
    assert await users.record_pin_failure(user.id, NOW + timedelta(hours=1)) == 0  # not below 0
    async with engine.connect() as conn:
        locked_at = (
            await conn.execute(
                select(tables.app_user.c.pin_locked_at).where(tables.app_user.c.id == user.id)
            )
        ).scalar_one()
    assert locked_at == NOW  # the first lock's time stands


@pytest.mark.asyncio
async def test_clear_pin_failures_zeroes_the_counter(engine: AsyncEngine) -> None:
    users = PgUserRepository(engine)
    user = await users.invite(NURSE_EMAIL, Role.ADMIN, None, None)
    await users.record_pin_failure(user.id, NOW)
    await users.record_pin_failure(user.id, NOW)

    await users.clear_pin_failures(user.id)

    assert await users.record_pin_failure(user.id, NOW) == MAX_PIN_TRIES - 1


@pytest.mark.asyncio
async def test_the_pin_hash_is_read_apart_and_never_in_a_repr(engine: AsyncEngine) -> None:
    users = PgUserRepository(engine)
    user = await users.invite(NURSE_EMAIL, Role.ADMIN, None, None)
    assert await users.pin_hash(user.id) is None

    await users.set_pin(user.id, hash_pin("246813"))

    stored = await users.pin_hash(user.id)
    assert stored is not None
    assert verify_pin(stored, "246813")
    assert "246813" not in stored
    assert stored not in repr(await users.get_user(user.id))
    assert await users.pin_hash(uuid4()) is None


@pytest.mark.asyncio
async def test_reset_pin_clears_the_lock_and_ends_the_sessions(engine: AsyncEngine) -> None:
    users, sessions = PgUserRepository(engine), PgSessionRepository(engine)
    user = await users.invite(NURSE_EMAIL, Role.ADMIN, None, None)
    await users.set_pin(user.id, hash_pin("246813"))
    for _ in range(MAX_PIN_TRIES):
        await users.record_pin_failure(user.id, NOW)
    session = await sessions.create(user.id, None, NOW, 12)

    reset = await users.reset_pin(user.id)

    assert (reset.has_pin, reset.pin_locked) == (False, False)
    assert await users.pin_hash(user.id) is None
    assert await sessions.get(session.token, NOW) is None
    assert await users.record_pin_failure(user.id, NOW) == MAX_PIN_TRIES - 1


@pytest.mark.asyncio
async def test_personas_seeded_with_the_demo_pin(engine: AsyncEngine) -> None:
    await seed(engine, CLOCK)
    users = PgUserRepository(engine)

    hashes = {await users.pin_hash(p.id) for p in DEMO_PERSONAS}

    assert len(hashes) == 1  # one public PIN, one hash
    (stored,) = hashes
    assert stored is not None
    assert verify_pin(stored, DEMO_PIN)
    for persona in DEMO_PERSONAS:
        user = await users.get_user(persona.id)
        assert (user.persona, user.status, user.has_pin) == (True, UserStatus.ACTIVE, True)
    await seed(engine, CLOCK)  # a second run keeps the hash it has
    assert {await users.pin_hash(p.id) for p in DEMO_PERSONAS} == {stored}


@pytest.mark.asyncio
async def test_session_lasts_the_facilitys_session_max_hours(engine: AsyncEngine) -> None:
    await seed(engine, CLOCK)
    us = (await PgFacilityRepository(engine, CLOCK).get_facility("us-demo")).profile
    nurse = next(p for p in DEMO_PERSONAS if p.facility_key == "us-demo")
    repo = PgSessionRepository(engine)

    new = await repo.create(nurse.id, None, NOW, us.session_max_hours)

    session = await repo.get(new.token, NOW)
    assert session is not None
    assert us.session_max_hours == 14
    assert session.expires_at == NOW + timedelta(hours=14)
    assert await repo.get(new.token, NOW + timedelta(hours=14)) is None


@pytest.mark.asyncio
async def test_admin_session_lasts_12_hours(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    repo = PgSessionRepository(engine)

    new = await repo.create(world.admin_id, None, NOW, 12)

    session = await repo.get(new.token, NOW)
    assert session is not None
    assert session.expires_at == NOW + SESSION_LIFETIME


@pytest.mark.asyncio
async def test_a_new_session_hides_its_tokens_and_starts_unverified(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    repo = PgSessionRepository(engine)

    new = await repo.create(world.admin_id, None, NOW, 12)

    assert new.token not in repr(new)
    assert new.csrf_token not in repr(new)
    session = await repo.get(new.token, NOW)
    assert session is not None
    assert session.csrf_token == new.csrf_token
    assert (session.created_at, session.last_active_at) == (NOW, NOW)
    assert (session.pin_verified_at, session.pin_failures) == (None, 0)


@pytest.mark.asyncio
async def test_touch_verify_and_session_pin_failures(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    repo = PgSessionRepository(engine)
    new = await repo.create(world.nurse_id, None, NOW, 12)
    later = NOW + timedelta(minutes=3)

    await repo.touch(new.token, later)
    touched = await repo.get(new.token, later)
    assert touched is not None
    assert (touched.last_active_at, touched.pin_verified_at) == (later, None)
    await repo.mark_pin_verified(new.token, later)
    verified = await repo.get(new.token, later)
    assert verified is not None
    assert verified.pin_verified_at == later
    assert verified.expires_at == NOW + timedelta(hours=12)  # an unlock never extends it
    left = [await repo.record_session_pin_failure(new.token) for _ in range(MAX_PIN_TRIES)]
    assert left == [4, 3, 2, 1, 0]
    assert await repo.record_session_pin_failure(new.token) == 0
    assert await repo.record_session_pin_failure("not-a-token") == 0
    failed = await repo.get(new.token, later)
    assert failed is not None
    assert failed.pin_failures == MAX_PIN_TRIES + 1


@pytest.mark.asyncio
async def test_delete_for_user_ends_every_session_of_that_user(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    repo = PgSessionRepository(engine)
    one = await repo.create(world.nurse_id, None, NOW, 12)
    two = await repo.create(world.nurse_id, None, NOW, 12)
    kept = await repo.create(world.admin_id, None, NOW, 12)

    await repo.delete_for_user(world.nurse_id)

    assert [await repo.get(t.token, NOW) for t in (one, two)] == [None, None]
    assert await repo.get(kept.token, NOW) is not None
