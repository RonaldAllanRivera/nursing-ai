"""Users, sessions and AI usage: the adapter-only repositories the API and worker need."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from pydantic import AwareDatetime
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from nursing_core.domain import DomainModel
from nursing_core.domain.errors import NotFound
from nursing_core.domain.notes import GenerationInfo
from nursing_core.domain.shifts import ShiftRef
from nursing_core.domain.users import Role
from nursing_core.storage import tables

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


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _shift_columns(shift: ShiftRef | None) -> dict[str, object]:
    return {
        "shift_code": shift.code if shift else None,
        "shift_label": shift.label if shift else None,
        "shift_starts_at": shift.starts_at if shift else None,
        "shift_ends_at": shift.ends_at if shift else None,
        "shift_date": shift.shift_date if shift else None,
        "shift_timezone": shift.timezone if shift else None,
    }


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
                    **_shift_columns(shift),
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
        shift = (
            ShiftRef(
                code=row.shift_code,
                label=row.shift_label,
                starts_at=row.shift_starts_at,
                ends_at=row.shift_ends_at,
                shift_date=row.shift_date,
                timezone=row.shift_timezone,
            )
            if row.shift_code is not None
            else None
        )
        return StoredSession(user_id=row.user_id, shift=shift, expires_at=row.expires_at)

    async def set_shift(self, token: str, shift: ShiftRef) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                update(_SESSION)
                .where(_SESSION.c.token_hash == _hash(token))
                .values(**_shift_columns(shift))
            )

    async def delete(self, token: str) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(delete(_SESSION).where(_SESSION.c.token_hash == _hash(token)))


class PgUsageRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def record(self, job_id: UUID | None, generation: GenerationInfo, at: datetime) -> None:
        """One row for one successful generation."""
        async with self._engine.begin() as conn:
            await conn.execute(
                insert(tables.ai_usage).values(
                    id=uuid4(),
                    job_id=job_id,
                    provider=generation.provider,
                    model=generation.model,
                    prompt_version=generation.prompt_version,
                    input_tokens=generation.input_tokens,
                    output_tokens=generation.output_tokens,
                    cost_usd=generation.cost_usd,
                    created_at=at,
                )
            )

    async def month_total(self, now: datetime) -> tuple[Decimal, int]:
        """The cost and number of calls in the UTC calendar month that contains `now`."""
        start = now.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        following = (start + timedelta(days=32)).replace(day=1)
        usage = tables.ai_usage
        async with self._engine.begin() as conn:
            row = (
                await conn.execute(
                    select(func.coalesce(func.sum(usage.c.cost_usd), 0), func.count()).where(
                        usage.c.created_at >= start, usage.c.created_at < following
                    )
                )
            ).one()
        return Decimal(row[0]), row[1]
