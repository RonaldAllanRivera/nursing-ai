"""Users and sessions: the adapter-only repositories the API needs to know who is signed in."""

import hashlib
import secrets
from datetime import datetime, timedelta
from uuid import UUID

from pydantic import AwareDatetime, Field
from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from nursing_core.domain import DomainModel
from nursing_core.domain.errors import NotFound
from nursing_core.domain.shifts import ShiftRef
from nursing_core.domain.users import Role
from nursing_core.storage import tables
from nursing_core.storage.rows import optional_shift_from_row, shift_columns

SESSION_LIFETIME = timedelta(hours=12)
_SESSION = tables.session


class StoredUser(DomainModel):
    id: UUID
    display_name: str
    initials: str
    role: Role
    facility_key: str | None  # None for the admin


class StoredSession(DomainModel):
    user_id: UUID
    shift: ShiftRef | None  # None for the admin
    expires_at: AwareDatetime
    csrf_token: str = Field(repr=False)  # the X-CSRF-Token value: never in a repr or a log


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class PgUserRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def get_user(self, user_id: UUID) -> StoredUser:
        async with self._engine.begin() as conn:
            row = (
                await conn.execute(
                    select(
                        tables.app_user.c.id,
                        tables.app_user.c.display_name,
                        tables.app_user.c.initials,
                        tables.app_user.c.role,
                        tables.facility.c.key.label("facility_key"),
                    )
                    .select_from(
                        tables.app_user.outerjoin(
                            tables.facility, tables.facility.c.id == tables.app_user.c.facility_id
                        )
                    )
                    .where(tables.app_user.c.id == user_id)
                )
            ).one_or_none()
        if row is None:
            raise NotFound("no such user")
        return StoredUser(
            id=row.id,
            display_name=row.display_name,
            initials=row.initials,
            role=Role(row.role),
            facility_key=row.facility_key,
        )


class PgSessionRepository:
    """Sessions keyed by the SHA-256 of the cookie's token; the token itself is never stored."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def create(self, user_id: UUID, shift: ShiftRef | None, now: datetime) -> str:
        """Starts a session that lasts 12 hours and returns its raw token (for the cookie)."""
        token = secrets.token_urlsafe(32)
        async with self._engine.begin() as conn:
            await conn.execute(
                insert(_SESSION).values(
                    token_hash=_hash(token),
                    user_id=user_id,
                    created_at=now,
                    expires_at=now + SESSION_LIFETIME,
                    csrf_token=secrets.token_urlsafe(32),
                    last_active_at=now,
                    **shift_columns(shift),
                )
            )
        return token

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
        shift = optional_shift_from_row(row)
        return StoredSession(
            user_id=row.user_id,
            shift=shift,
            expires_at=row.expires_at,
            csrf_token=row.csrf_token,
        )

    async def set_shift(self, token: str, shift: ShiftRef) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                update(_SESSION)
                .where(_SESSION.c.token_hash == _hash(token))
                .values(**shift_columns(shift))
            )

    async def delete(self, token: str) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(delete(_SESSION).where(_SESSION.c.token_hash == _hash(token)))
