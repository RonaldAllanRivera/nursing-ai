"""The facility repository: the region profile as the admin last saved it, and its history."""

from uuid import UUID, uuid4

from sqlalchemy import ColumnElement, delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from nursing_core.domain.errors import NotFound, StaleVersion
from nursing_core.domain.facility import FacilityProfile, FacilitySettings, StoredFacility
from nursing_core.ports import Clock
from nursing_core.storage import tables
from nursing_core.storage.rows import facility_columns, shift_rows

_FACILITY = tables.facility
_SHIFT = tables.shift_definition


async def load_facilities(
    conn: AsyncConnection, *conditions: ColumnElement[bool]
) -> list[StoredFacility]:
    """The facilities matching the conditions, by key, each with its shifts in position order."""
    rows = (
        await conn.execute(select(_FACILITY).where(*conditions).order_by(_FACILITY.c.key))
    ).all()
    shifts = (
        await conn.execute(
            select(_SHIFT)
            .where(_SHIFT.c.facility_id.in_([row.id for row in rows]))
            .order_by(_SHIFT.c.facility_id, _SHIFT.c.position)
        )
    ).all()
    return [
        StoredFacility(
            profile=FacilityProfile.model_validate(
                {
                    "key": row.key,
                    "name": row.name,
                    "timezone": row.timezone,
                    "locale": row.locale,
                    "day_starts_at": row.day_starts_at,
                    "shifts": [
                        {
                            "code": s.code,
                            "label": s.label,
                            "starts_local": s.starts_local,
                            "ends_local": s.ends_local,
                            "ink": s.ink,
                        }
                        for s in shifts
                        if s.facility_id == row.id
                    ],
                    "note_formats": row.note_formats,
                    "default_note_format": row.default_note_format,
                    "units": {
                        "temperature": row.unit_temperature,
                        "weight": row.unit_weight,
                        "volume": row.unit_volume,
                    },
                    "clock": row.clock,
                    "session_max_hours": row.session_max_hours,
                }
            ),
            version=row.version,
        )
        for row in rows
    ]


class PgFacilityRepository:
    def __init__(self, engine: AsyncEngine, clock: Clock) -> None:
        self._engine = engine
        self._clock = clock

    async def list_facilities(self) -> list[StoredFacility]:
        async with self._engine.begin() as conn:
            return await load_facilities(conn)

    async def get_facility(self, key: str) -> StoredFacility:
        async with self._engine.begin() as conn:
            found = await load_facilities(conn, _FACILITY.c.key == key)
        if not found:
            raise NotFound("no such facility")
        return found[0]

    async def update_facility(
        self, key: str, settings: FacilitySettings, expected_version: int, changed_by: UUID
    ) -> StoredFacility:
        """Bumps the version, rewrites the shift rows and appends the history row, together."""
        now = self._clock.now()
        async with self._engine.begin() as conn:
            current = (
                await conn.execute(
                    select(_FACILITY.c.id, _FACILITY.c.version)
                    .where(_FACILITY.c.key == key)
                    .with_for_update()
                )
            ).one_or_none()
            if current is None:
                raise NotFound("no such facility")
            if current.version != expected_version:
                raise StaleVersion("the facility was changed by someone else")
            version = current.version + 1
            await conn.execute(
                update(_FACILITY)
                .where(_FACILITY.c.id == current.id)
                .values(
                    **facility_columns(settings),
                    version=version,
                    updated_by=changed_by,
                    updated_at=now,
                )
            )
            await conn.execute(delete(_SHIFT).where(_SHIFT.c.facility_id == current.id))
            await conn.execute(insert(_SHIFT), shift_rows(current.id, settings.shifts))
            await conn.execute(
                insert(tables.facility_change).values(
                    id=uuid4(),
                    facility_id=current.id,
                    version=version,
                    changed_by=changed_by,
                    changed_at=now,
                    settings=settings.model_dump(mode="json"),
                )
            )
            return (await load_facilities(conn, _FACILITY.c.id == current.id))[0]
