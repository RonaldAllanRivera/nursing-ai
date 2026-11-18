"""Users and sessions: the adapter-only repositories the API needs to know who is signed in.

A user row is a demo persona or a person on the invite list. The PIN's hash is never part of
`StoredUser`: a repr or a log line of a user must not be able to leak it, so the hash is read
through `PgUserRepository.pin_hash` by the one caller that checks a PIN. Methods that write a
time take it from the caller; nothing here reads the clock.
"""

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field
from sqlalchemy import Select, delete, func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from nursing_core.auth.pins import MAX_PIN_TRIES
from nursing_core.domain import DomainModel
from nursing_core.domain.errors import EmailTaken, IdentityMismatch, NotFound
from nursing_core.domain.shifts import ShiftRef
from nursing_core.domain.users import Role, UserStatus
from nursing_core.storage import tables
from nursing_core.storage.rows import optional_shift_from_row, shift_columns

SESSION_LIFETIME = timedelta(hours=12)  # the admin's session; a facility's own length is its own
_SESSION = tables.session
_USER = tables.app_user


class StoredUser(DomainModel):
    id: UUID
    display_name: str
    initials: str
    role: Role
    facility_key: str | None  # None for the admin
    persona: bool  # a demo persona (no Google account, the published demo PIN)
    email: str | None  # lowercase; None for a persona
    status: UserStatus
    has_pin: bool
    pin_locked: bool  # five wrong PINs: a head nurse or the admin resets it in person


class StoredSession(DomainModel):
    user_id: UUID
    shift: ShiftRef | None  # None for the admin
    created_at: AwareDatetime
    expires_at: AwareDatetime
    csrf_token: str = Field(repr=False)  # the X-CSRF-Token value: never in a repr or a log
    pin_verified_at: AwareDatetime | None
    last_active_at: AwareDatetime
    pin_failures: int  # wrong PINs typed in this session (what counts for a demo persona)


class NewSession(DomainModel):
    """What starting a session hands back: the cookie's token and the CSRF token."""

    token: str = Field(repr=False)
    csrf_token: str = Field(repr=False)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _tries_left(failures: int) -> int:
    return max(0, MAX_PIN_TRIES - failures)


def _normal(email: str) -> str:
    return email.strip().lower()


def _user_query() -> Select[*tuple[Any, ...]]:
    return select(
        _USER.c.id,
        _USER.c.display_name,
        _USER.c.initials,
        _USER.c.role,
        _USER.c.persona,
        _USER.c.email,
        _USER.c.google_sub,
        _USER.c.revoked_at,
        _USER.c.pin_hash,
        _USER.c.pin_locked_at,
        tables.facility.c.key.label("facility_key"),
    ).select_from(_USER.outerjoin(tables.facility, tables.facility.c.id == _USER.c.facility_id))


def _user_from_row(row: Any) -> StoredUser:
    if row.revoked_at is not None:
        status = UserStatus.REVOKED
    elif row.google_sub is not None or row.persona:
        status = UserStatus.ACTIVE
    else:
        status = UserStatus.INVITED
    return StoredUser(
        id=row.id,
        display_name=row.display_name,
        initials=row.initials,
        role=Role(row.role),
        facility_key=row.facility_key,
        persona=row.persona,
        email=row.email,
        status=status,
        has_pin=row.pin_hash is not None,
        pin_locked=row.pin_locked_at is not None,
    )


async def _load_user(conn: AsyncConnection, user_id: UUID) -> StoredUser:
    row = (await conn.execute(_user_query().where(_USER.c.id == user_id))).one_or_none()
    if row is None:
        raise NotFound("no such user")
    return _user_from_row(row)


class PgUserRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def get_user(self, user_id: UUID) -> StoredUser:
        async with self._engine.begin() as conn:
            return await _load_user(conn, user_id)

    async def get_user_by_email(self, email: str) -> StoredUser | None:
        """The invited or signed-in user with this email, however it is cased."""
        async with self._engine.begin() as conn:
            row = (
                await conn.execute(_user_query().where(_USER.c.email == _normal(email)))
            ).one_or_none()
        return None if row is None else _user_from_row(row)

    async def list_staff(self, facility_key: str | None) -> list[StoredUser]:
        """Everyone invited, revoked ones too, by email: one facility's, or None for all.

        Demo personas are never listed.
        """
        query = _user_query().where(_USER.c.persona.is_(False)).order_by(_USER.c.email)
        if facility_key is not None:
            query = query.where(tables.facility.c.key == facility_key)
        async with self._engine.begin() as conn:
            return [_user_from_row(row) for row in (await conn.execute(query)).all()]

    async def invite(
        self, email: str, role: Role, facility_key: str | None, invited_by: UUID | None
    ) -> StoredUser:
        """Adds an invite. Its name and initials are placeholders until the first Google sign-in.

        Raises `EmailTaken` when the email belongs to anyone, revoked or not.
        """
        address = _normal(email)
        async with self._engine.begin() as conn:
            facility_id = None
            if facility_key is not None:
                facility_id = (
                    await conn.execute(
                        select(tables.facility.c.id).where(tables.facility.c.key == facility_key)
                    )
                ).scalar_one_or_none()
                if facility_id is None:
                    raise NotFound("no such facility")
            user_id = uuid4()
            try:
                async with conn.begin_nested():
                    await conn.execute(
                        insert(_USER).values(
                            id=user_id,
                            display_name=address,
                            initials=address[:1].upper(),
                            role=role.value,
                            facility_id=facility_id,
                            email=address,
                            invited_by=invited_by,
                        )
                    )
            except IntegrityError as error:
                raise EmailTaken("that email is already on the list") from error
            return await _load_user(conn, user_id)

    async def bind_google(
        self, user_id: UUID, sub: str, display_name: str, initials: str
    ) -> StoredUser:
        """The first Google sign-in: binds the account and takes its name and initials.

        A later call with the same `sub` changes nothing. Another `sub` for this user, or a `sub`
        that belongs to another user, raises `IdentityMismatch`.
        """
        async with self._engine.begin() as conn:
            current = (
                await conn.execute(
                    select(_USER.c.google_sub).where(_USER.c.id == user_id).with_for_update()
                )
            ).one_or_none()
            if current is None:
                raise NotFound("no such user")
            if current.google_sub is not None:
                if current.google_sub != sub:
                    raise IdentityMismatch("another Google account is bound to this email")
                return await _load_user(conn, user_id)
            try:
                async with conn.begin_nested():
                    await conn.execute(
                        update(_USER)
                        .where(_USER.c.id == user_id)
                        .values(google_sub=sub, display_name=display_name, initials=initials)
                    )
            except IntegrityError as error:
                raise IdentityMismatch("that Google account belongs to another user") from error
            return await _load_user(conn, user_id)

    async def revoke(self, user_id: UUID, now: datetime) -> StoredUser:
        """Ends the user's access and sessions; the row stays. Revoking twice changes nothing."""
        async with self._engine.begin() as conn:
            await _load_user(conn, user_id)
            await conn.execute(
                update(_USER)
                .where(_USER.c.id == user_id, _USER.c.revoked_at.is_(None))
                .values(revoked_at=now)
            )
            await conn.execute(delete(_SESSION).where(_SESSION.c.user_id == user_id))
            return await _load_user(conn, user_id)

    async def ensure_bootstrap_admin(self, email: str) -> StoredUser | None:
        """Makes the configured email an admin, only while no active Google admin exists.

        Returns that admin's row, or None when an active Google admin exists, or when the email
        belongs to a nurse or a revoked row (neither is promoted or revived).
        """
        address = _normal(email)
        async with self._engine.begin() as conn:
            active = await conn.scalar(
                select(func.count())
                .select_from(_USER)
                .where(
                    _USER.c.role == Role.ADMIN.value,
                    _USER.c.persona.is_(False),
                    _USER.c.revoked_at.is_(None),
                    _USER.c.google_sub.is_not(None),
                )
            )
            if active:
                return None
            row = (await conn.execute(_user_query().where(_USER.c.email == address))).one_or_none()
            if row is not None:
                found = _user_from_row(row)
                is_admin = found.role is Role.ADMIN and found.status is not UserStatus.REVOKED
                return found if is_admin else None
        try:
            return await self.invite(address, Role.ADMIN, None, None)
        except EmailTaken:  # another sign-in made it first
            return None

    async def pin_hash(self, user_id: UUID) -> str | None:
        """The stored hash, for the one caller that verifies a PIN; None when no PIN is set."""
        async with self._engine.begin() as conn:
            return await conn.scalar(select(_USER.c.pin_hash).where(_USER.c.id == user_id))

    async def set_pin(self, user_id: UUID, pin_hash: str) -> bool:
        """Stores a PIN hash the caller made (hashing is slow: it runs off the event loop).

        Writes only while no PIN is set, and says whether it wrote: two requests racing to set
        the first PIN can't both win. The caller has checked the PIN's format.
        """
        async with self._engine.begin() as conn:
            written = await conn.scalar(
                update(_USER)
                .where(_USER.c.id == user_id, _USER.c.pin_hash.is_(None))
                .values(pin_hash=pin_hash, pin_failures=0, pin_locked_at=None)
                .returning(_USER.c.id)
            )
        return written is not None

    async def claim_pin_try(self, user_id: UUID) -> int | None:
        """Takes one of the user's five tries before the PIN is verified; returns the tries left
        if this guess is wrong, or None when no try is left (the PIN is locked, or the user is
        a persona, whose tries count on the session).

        Claiming first is what bounds parallel guessing: only five requests can ever verify.
        """
        async with self._engine.begin() as conn:
            failures = await conn.scalar(
                update(_USER)
                .where(
                    _USER.c.id == user_id,
                    _USER.c.persona.is_(False),
                    _USER.c.pin_locked_at.is_(None),
                    _USER.c.pin_failures < MAX_PIN_TRIES,
                )
                .values(pin_failures=_USER.c.pin_failures + 1)
                .returning(_USER.c.pin_failures)
            )
        return None if failures is None else _tries_left(failures)

    async def lock_pin(self, user_id: UUID, now: datetime) -> bool:
        """Locks the PIN at `now` once its five tries are used up; says whether it locked.

        Only the call that actually locks reports True (and logs the event): a PIN already
        locked, or with tries left because a right guess cleared the counter, is not touched.
        """
        async with self._engine.begin() as conn:
            locked = await conn.scalar(
                update(_USER)
                .where(
                    _USER.c.id == user_id,
                    _USER.c.persona.is_(False),
                    _USER.c.pin_locked_at.is_(None),
                    _USER.c.pin_failures >= MAX_PIN_TRIES,
                )
                .values(pin_locked_at=now)
                .returning(_USER.c.id)
            )
        return locked is not None

    async def clear_pin_failures(self, user_id: UUID) -> bool:
        """A right PIN: the tries start again, unless the PIN is locked (a right guess racing
        the fifth wrong one must not unlock it). Says whether it cleared."""
        async with self._engine.begin() as conn:
            cleared = await conn.scalar(
                update(_USER)
                .where(
                    _USER.c.id == user_id,
                    _USER.c.persona.is_(False),
                    _USER.c.pin_locked_at.is_(None),
                )
                .values(pin_failures=0)
                .returning(_USER.c.id)
            )
        return cleared is not None

    async def reset_pin(self, user_id: UUID) -> StoredUser:
        """Clears the PIN and its lock, and ends the user's sessions.

        The new PIN is chosen after a fresh Google sign-in, so a session left open on a ward
        computer cannot be used to set it.
        """
        async with self._engine.begin() as conn:
            await _load_user(conn, user_id)
            await conn.execute(
                update(_USER)
                .where(_USER.c.id == user_id)
                .values(pin_hash=None, pin_failures=0, pin_locked_at=None)
            )
            await conn.execute(delete(_SESSION).where(_SESSION.c.user_id == user_id))
            return await _load_user(conn, user_id)


class PgSessionRepository:
    """Sessions keyed by the SHA-256 of the cookie's token; the token itself is never stored."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def create(
        self, user_id: UUID, shift: ShiftRef | None, now: datetime, max_hours: int
    ) -> NewSession:
        """Starts a session that lasts `max_hours` (its facility's setting; 12 for the admin)."""
        new = NewSession(token=secrets.token_urlsafe(32), csrf_token=secrets.token_urlsafe(32))
        async with self._engine.begin() as conn:
            await conn.execute(
                insert(_SESSION).values(
                    token_hash=_hash(new.token),
                    user_id=user_id,
                    created_at=now,
                    expires_at=now + timedelta(hours=max_hours),
                    csrf_token=new.csrf_token,
                    last_active_at=now,
                    **shift_columns(shift),
                )
            )
        return new

    async def get(self, token: str, now: datetime) -> StoredSession | None:
        """The live session for this token, or None when it is unknown or has expired."""
        async with self._engine.begin() as conn:
            row = (
                await conn.execute(
                    select(_SESSION).where(
                        _SESSION.c.token_hash == _hash(token), _SESSION.c.expires_at > now
                    )
                )
            ).one_or_none()
        if row is None:
            return None
        return StoredSession(
            user_id=row.user_id,
            shift=optional_shift_from_row(row),
            created_at=row.created_at,
            expires_at=row.expires_at,
            csrf_token=row.csrf_token,
            pin_verified_at=row.pin_verified_at,
            last_active_at=row.last_active_at,
            pin_failures=row.pin_failures,
        )

    async def set_shift(self, token: str, shift: ShiftRef) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                update(_SESSION)
                .where(_SESSION.c.token_hash == _hash(token))
                .values(**shift_columns(shift))
            )

    async def touch(self, token: str, now: datetime) -> None:
        """Marks the session active at `now` (the idle lock counts from here)."""
        async with self._engine.begin() as conn:
            await conn.execute(
                update(_SESSION)
                .where(_SESSION.c.token_hash == _hash(token))
                .values(last_active_at=now)
            )

    async def mark_pin_verified(self, token: str, now: datetime) -> str | None:
        """The PIN was right: the session is verified and active at `now`, under a new token.

        Returns the new token for the cookie, or None when the session is gone. A cookie copied
        while the session waited for its PIN opens nothing afterwards. It is the same session:
        its expiry and its CSRF token stay.
        """
        new_token = secrets.token_urlsafe(32)
        async with self._engine.begin() as conn:
            verified = await conn.scalar(
                update(_SESSION)
                .where(_SESSION.c.token_hash == _hash(token))
                .values(token_hash=_hash(new_token), pin_verified_at=now, last_active_at=now)
                .returning(_SESSION.c.user_id)
            )
        return None if verified is None else new_token

    async def claim_session_pin_try(self, token: str) -> int | None:
        """Takes one of this session's five tries before the PIN is verified (a persona's tries
        count here); returns the tries left if the guess is wrong, or None when the session is
        unknown or has none left."""
        async with self._engine.begin() as conn:
            failures = await conn.scalar(
                update(_SESSION)
                .where(
                    _SESSION.c.token_hash == _hash(token), _SESSION.c.pin_failures < MAX_PIN_TRIES
                )
                .values(pin_failures=_SESSION.c.pin_failures + 1)
                .returning(_SESSION.c.pin_failures)
            )
        return None if failures is None else _tries_left(failures)

    async def clear_session_pin_failures(self, token: str) -> bool:
        """A right PIN: this session's tries start again. False when the session is gone."""
        async with self._engine.begin() as conn:
            cleared = await conn.scalar(
                update(_SESSION)
                .where(_SESSION.c.token_hash == _hash(token))
                .values(pin_failures=0)
                .returning(_SESSION.c.user_id)
            )
        return cleared is not None

    async def delete(self, token: str) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(delete(_SESSION).where(_SESSION.c.token_hash == _hash(token)))

    async def delete_for_user(self, user_id: UUID) -> None:
        """Ends every session of this user."""
        async with self._engine.begin() as conn:
            await conn.execute(delete(_SESSION).where(_SESSION.c.user_id == user_id))
