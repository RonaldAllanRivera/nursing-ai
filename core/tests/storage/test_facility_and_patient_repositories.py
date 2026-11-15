"""The facility and patient repositories against a real migrated database."""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from nursing_core.clock import FixedClock
from nursing_core.domain.errors import NotFound, StaleVersion
from nursing_core.domain.facility import FacilitySettings, ShiftDefinition, ShiftInk, preset
from nursing_core.domain.patient import PatientRecord, PatientSummary
from nursing_core.domain.units import Ucum
from nursing_core.storage import tables
from nursing_core.storage.repositories import PgFacilityRepository, PgPatientRepository
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from .world import NOW, add_patient, build_world

CLOCK = FixedClock(datetime(2026, 11, 12, 9, 0, tzinfo=UTC))


def _edited(name: str) -> FacilitySettings:
    us = preset("US", "x", name)
    return FacilitySettings.model_validate(us.model_dump(exclude={"key"}))


@pytest.mark.asyncio
async def test_facility_round_trips_its_profile_and_shifts(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    repo = PgFacilityRepository(engine, CLOCK)

    stored = await repo.get_facility(world.profile.key)

    assert stored.profile == world.profile
    assert stored.version == 1
    assert [s.profile.key for s in await repo.list_facilities()] == [world.profile.key]


@pytest.mark.asyncio
async def test_unknown_facility_is_not_found(engine: AsyncEngine) -> None:
    with pytest.raises(NotFound):
        await PgFacilityRepository(engine, CLOCK).get_facility("nowhere")


@pytest.mark.asyncio
async def test_update_facility_bumps_version_rewrites_shifts_and_keeps_history(
    engine: AsyncEngine,
) -> None:
    world = await build_world(engine)
    repo = PgFacilityRepository(engine, CLOCK)
    settings = _edited("SYNTHETIC Renamed")

    stored = await repo.update_facility(world.profile.key, settings, 1, world.admin_id)

    assert stored.version == 2
    assert stored.profile.name == "SYNTHETIC Renamed"
    assert stored.profile.shifts == settings.shifts
    assert stored.profile.units.weight is None
    assert stored.profile.key == world.profile.key
    assert await repo.get_facility(world.profile.key) == stored
    async with engine.connect() as conn:
        history = (
            await conn.execute(
                select(tables.facility_change.c.version, tables.facility_change.c.changed_by)
                .where(tables.facility_change.c.facility_id == world.facility_id)
                .order_by(tables.facility_change.c.version)
            )
        ).all()
        settings_json = await conn.scalar(
            select(tables.facility_change.c.settings).where(
                tables.facility_change.c.facility_id == world.facility_id,
                tables.facility_change.c.version == 2,
            )
        )
        shifts = await conn.scalar(
            select(func.count()).where(tables.shift_definition.c.facility_id == world.facility_id)
        )
    assert [(row.version, row.changed_by) for row in history] == [(1, None), (2, world.admin_id)]
    assert FacilitySettings.model_validate(settings_json) == settings
    assert shifts == len(settings.shifts)


@pytest.mark.asyncio
async def test_update_facility_with_stale_version_changes_nothing(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    repo = PgFacilityRepository(engine, CLOCK)
    await repo.update_facility(world.profile.key, _edited("SYNTHETIC One"), 1, world.admin_id)

    with pytest.raises(StaleVersion):
        await repo.update_facility(world.profile.key, _edited("SYNTHETIC Two"), 1, world.admin_id)

    stored = await repo.get_facility(world.profile.key)
    assert (stored.version, stored.profile.name) == (2, "SYNTHETIC One")


@pytest.mark.asyncio
async def test_update_unknown_facility_is_not_found(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    with pytest.raises(NotFound):
        await PgFacilityRepository(engine, CLOCK).update_facility(
            "nowhere", _edited("SYNTHETIC X"), 1, world.admin_id
        )


@pytest.mark.asyncio
async def test_update_facility_keeps_shifts_in_the_order_given(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    settings = world.profile.model_copy(
        update={
            "shifts": [
                ShiftDefinition(
                    code="night",
                    label="Night",
                    starts_local=time(22),
                    ends_local=time(6),
                    ink=ShiftInk.RED,
                ),
                ShiftDefinition(
                    code="day",
                    label="Day",
                    starts_local=time(6),
                    ends_local=time(22),
                    ink=ShiftInk.BLUE,
                ),
            ],
            "units": world.profile.units.model_copy(update={"temperature": Ucum.DEG_F}),
        }
    )
    edit = FacilitySettings.model_validate(settings.model_dump(exclude={"key"}))
    repo = PgFacilityRepository(engine, CLOCK)

    stored = await repo.update_facility(world.profile.key, edit, 1, world.admin_id)

    assert [s.code for s in stored.profile.shifts] == ["night", "day"]
    assert stored.profile.units.temperature is Ucum.DEG_F


@pytest.mark.asyncio
async def test_get_patient_returns_identity_context_and_facility(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    repo = PgPatientRepository(engine, CLOCK)
    case = world.case

    record = await repo.get_patient(world.patient_id)

    assert isinstance(record, PatientRecord)
    assert record.encounter_id == world.encounter_id
    assert record.identity == case.patient
    assert [r.name for r in record.identity.relatives] == [r.name for r in case.patient.relatives]
    assert record.context == case.context
    assert record.facility == world.profile
    assert record.summary == PatientSummary(
        id=case.patient_id,
        display_name=case.display_name,
        age=case.age,
        sex=case.sex,
        ward=case.ward,
        bed_label=case.bed_label,
        facility_key=case.facility_key,
    )
    assert await repo.get_patient_by_encounter(world.encounter_id) == record


@pytest.mark.asyncio
async def test_age_is_counted_in_the_facility_timezone(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    born = world.case.patient.birth_date
    birthday = datetime(born.year + 40, born.month, born.day, tzinfo=ZoneInfo("Asia/Manila"))
    before = PgPatientRepository(engine, FixedClock(birthday - timedelta(minutes=1)))
    after = PgPatientRepository(engine, FixedClock(birthday))

    assert (await before.get_patient(world.patient_id)).summary.age == 39
    assert (await after.get_patient(world.patient_id)).summary.age == 40


@pytest.mark.asyncio
async def test_unknown_patient_and_encounter_are_not_found(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    repo = PgPatientRepository(engine, CLOCK)
    with pytest.raises(NotFound):
        await repo.get_patient(world.nurse_id)
    with pytest.raises(NotFound):
        await repo.get_patient_by_encounter(world.nurse_id)


@pytest.mark.asyncio
async def test_list_patients_sorts_by_ward_bed_and_name_and_skips_discharged(
    engine: AsyncEngine,
) -> None:
    world = await build_world(engine)
    ward = world.case.ward
    a_id, _ = await add_patient(
        engine,
        world,
        display_name="Demo patient Z",
        ward="Alpha Ward",
        bed_label="3",
        record_number="R-1",
    )
    b_id, _ = await add_patient(
        engine, world, display_name="Demo patient Y", ward=ward, bed_label="01", record_number="R-2"
    )
    gone_id, gone_encounter = await add_patient(
        engine, world, display_name="Demo patient W", ward=ward, bed_label="02", record_number="R-3"
    )
    async with engine.begin() as conn:
        await conn.execute(
            update(tables.encounter)
            .where(tables.encounter.c.id == gone_encounter)
            .values(discharged_at=NOW)
        )
    repo = PgPatientRepository(engine, CLOCK)

    listed = await repo.list_patients(world.profile.key)

    assert [p.id for p in listed] == [a_id, b_id, world.patient_id]
    assert gone_id not in [p.id for p in listed]
    assert await repo.list_patients("nowhere") == []
    with pytest.raises(NotFound):
        await repo.get_patient(gone_id)
