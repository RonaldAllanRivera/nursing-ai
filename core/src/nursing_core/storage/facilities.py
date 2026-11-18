"""The facility repository: the region profile as the admin last saved it, and its history."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import ColumnElement, delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from nursing_core.demo import DEMO_FACILITIES
from nursing_core.domain.errors import NotFound, StaleVersion
from nursing_core.domain.facility import FacilityProfile, FacilitySettings, StoredFacility
from nursing_core.domain.shifts import shift_containing
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


async def _write_version(
    conn: AsyncConnection,
    facility_id: UUID,
    version: int,
    settings: FacilitySettings,
    by: UUID | None,
    now: datetime,
    *,
    reset: bool,
) -> StoredFacility:
    """The one place a facility's new version is written, on a row the caller has locked.

    Updates the facility columns, rewrites the shift rows and appends the history row (`reset`
    marks a demo reset, which has no author), then returns the facility as stored.
    """
    await conn.execute(
        update(_FACILITY)
        .where(_FACILITY.c.id == facility_id)
        .values(**facility_columns(settings), version=version, updated_by=by, updated_at=now)
    )
    await conn.execute(delete(_SHIFT).where(_SHIFT.c.facility_id == facility_id))
    await conn.execute(insert(_SHIFT), shift_rows(facility_id, settings.shifts))
    await conn.execute(
        insert(tables.facility_change).values(
            id=uuid4(),
            facility_id=facility_id,
            version=version,
            changed_by=by,
            changed_at=now,
            settings=settings.model_dump(mode="json"),
            reset=reset,
        )
    )
    return (await load_facilities(conn, _FACILITY.c.id == facility_id))[0]


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
            return await _write_version(
                conn, current.id, current.version + 1, settings, changed_by, now, reset=False
            )

    async def reset_to_preset(
        self, key: str, now: datetime, expected_version: int
    ) -> StoredFacility:
        """Puts a demo facility's settings, name included, back to its preset and records it as a
        `reset` change with no author.

        Like `update_facility`, it refuses a save that landed meanwhile (`StaleVersion`, checked
        under the row lock). A facility with no preset is `NotFound`.
        """
        reset = await self._reset(key, now, expected_version=expected_version, only_if_stale=False)
        if reset is None:  # unreachable: only the stale check can decline
            raise NotFound("no such facility")
        return reset

    async def reset_stale_to_presets(self, now: datetime) -> list[str]:
        """Puts back every demo facility a persona changed before its current nursing day began.

        The facility's own timezone and shifts decide where a nursing day starts. A facility whose
        latest change is already a reset, or was made by an invited person (or is the seed), is
        left alone. Returns the keys it reset.
        """
        done: list[str] = []
        for preset in DEMO_FACILITIES:
            if (
                await self._reset(preset.key, now, expected_version=None, only_if_stale=True)
                is not None
            ):
                done.append(preset.key)
        return done

    async def _reset(
        self, key: str, now: datetime, *, expected_version: int | None, only_if_stale: bool
    ) -> StoredFacility | None:
        preset = next((p for p in DEMO_FACILITIES if p.key == key), None)
        if preset is None:
            raise NotFound("no preset for this facility")
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
            if expected_version is not None and current.version != expected_version:
                raise StaleVersion("the facility was changed by someone else")
            if only_if_stale and not await _persona_changed_before_today(
                conn, current.id, key, now
            ):
                return None
            settings = FacilitySettings.model_validate(preset.model_dump(exclude={"key"}))
            return await _write_version(
                conn, current.id, current.version + 1, settings, None, now, reset=True
            )


async def _persona_changed_before_today(
    conn: AsyncConnection, facility_id: UUID, key: str, now: datetime
) -> bool:
    """True when a persona made the latest change, before the nursing day `now` falls in."""
    latest = (
        await conn.execute(
            select(
                tables.facility_change.c.changed_at,
                tables.facility_change.c.reset,
                tables.app_user.c.persona,
            )
            .select_from(
                tables.facility_change.outerjoin(
                    tables.app_user, tables.app_user.c.id == tables.facility_change.c.changed_by
                )
            )
            .where(tables.facility_change.c.facility_id == facility_id)
            .order_by(tables.facility_change.c.version.desc())
            .limit(1)
        )
    ).one_or_none()
    if latest is None or latest.reset or not latest.persona:
        return False
    profile = (await load_facilities(conn, _FACILITY.c.key == key))[0].profile
    return (
        shift_containing(latest.changed_at, profile).shift_date
        < shift_containing(now, profile).shift_date
    )
