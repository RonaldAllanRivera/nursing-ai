"""The synthetic seed: two demo facilities, their staff and patients, safe to run again."""

import asyncio
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from nursing_core.clock import FixedClock
from nursing_core.db import create_engine
from nursing_core.demo import DEMO_FACILITIES, DEMO_PERSONAS, load_demo_cases
from nursing_core.domain.patient import PatientRecord
from nursing_core.domain.units import Ucum
from nursing_core.domain.users import Role
from nursing_core.storage import tables
from nursing_core.storage.repositories import (
    PgFacilityRepository,
    PgPatientRepository,
    PgUserRepository,
)
from nursing_core.storage.seed import seed
from nursing_core.storage.testdb import fresh_database
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

CLOCK = FixedClock(datetime(2026, 11, 12, 9, 0, tzinfo=UTC))
SEEDED_TABLES = [
    tables.facility,
    tables.shift_definition,
    tables.facility_change,
    tables.app_user,
    tables.ward,
    tables.bed,
    tables.patient,
    tables.patient_relative,
    tables.encounter,
    tables.patient_context,
]


@pytest_asyncio.fixture
async def seeded(engine: AsyncEngine) -> AsyncEngine:
    await seed(engine, CLOCK)
    return engine


async def record(engine: AsyncEngine, facility_key: str, record_number: str) -> PatientRecord:
    """The seeded patient with this record number, read back through the repository."""
    repo = PgPatientRepository(engine, CLOCK)
    for summary in await repo.list_patients(facility_key):
        found = await repo.get_patient(summary.id)
        if found.identity.record_number == record_number:
            return found
    raise AssertionError(f"no seeded patient {record_number}")


async def counts(engine: AsyncEngine) -> dict[str, int]:
    async with engine.begin() as conn:
        return {
            table.name: (await conn.execute(select(func.count()).select_from(table))).scalar_one()
            for table in [*SEEDED_TABLES, tables.rough_note, tables.draft_job, tables.note]
        }


async def all_records(engine: AsyncEngine) -> list[PatientRecord]:
    repo = PgPatientRepository(engine, CLOCK)
    return [
        await repo.get_patient(summary.id)
        for facility in DEMO_FACILITIES
        for summary in await repo.list_patients(facility.key)
    ]


@pytest.mark.asyncio
async def test_seed_is_repeatable(
    seeded: AsyncEngine, postgres_url: str, template_database: str
) -> None:
    first = await counts(seeded)
    first_records = await all_records(seeded)
    await seed(seeded, CLOCK)
    assert await counts(seeded) == first
    assert await all_records(seeded) == first_records

    # A different day, a different database: the same patients with the same ids.
    async with fresh_database(postgres_url, template_database) as url:
        other = create_engine(url)
        try:
            await seed(other, FixedClock(datetime(2027, 3, 1, 4, 0, tzinfo=UTC)))
            other_records = await all_records(other)
        finally:
            await other.dispose()
    assert [r.summary.id for r in other_records] == [r.summary.id for r in first_records]
    # Only the age moves with the clock; everything the seed wrote is the same.
    assert [(r.identity, r.context, r.encounter_id) for r in other_records] == [
        (r.identity, r.context, r.encounter_id) for r in first_records
    ]


@pytest.mark.asyncio
async def test_seed_writes_no_notes_jobs_or_sessions(seeded: AsyncEngine) -> None:
    found = await counts(seeded)
    assert found["rough_note"] == found["draft_job"] == found["note"] == 0


@pytest.mark.asyncio
async def test_seed_includes_every_demo_case(seeded: AsyncEngine) -> None:
    for case in load_demo_cases():
        repo = PgPatientRepository(seeded, FixedClock(case.rough_note.written_at))
        found = await repo.get_patient(case.patient_id)
        assert found.identity == case.patient
        assert found.context == case.context
        assert found.encounter_id == case.rough_note.encounter_id
        assert found.facility.key == case.facility_key
        summary = found.summary
        assert (summary.display_name, summary.age, summary.sex) == (
            case.display_name,
            case.age,
            case.sex,
        )
        assert (summary.ward, summary.bed_label) == (case.ward, case.bed_label)
        assert summary.facility_key == case.facility_key


@pytest.mark.asyncio
async def test_seed_has_both_facilities_with_their_presets(seeded: AsyncEngine) -> None:
    facilities = PgFacilityRepository(seeded, CLOCK)
    for profile in DEMO_FACILITIES:
        stored = await facilities.get_facility(profile.key)
        assert stored.profile == profile
        assert stored.version == 1
    async with seeded.begin() as conn:
        history = (
            await conn.execute(
                select(tables.facility.c.key, tables.facility_change)
                .join(
                    tables.facility_change,
                    tables.facility_change.c.facility_id == tables.facility.c.id,
                )
                .order_by(tables.facility.c.key)
            )
        ).all()
    assert [(row.key, row.version, row.changed_by) for row in history] == [
        ("ph-demo", 1, None),
        ("us-demo", 1, None),
    ]
    for row, profile in zip(history, DEMO_FACILITIES, strict=True):
        assert row.settings == profile.model_dump(mode="json", exclude={"key"})

    users = PgUserRepository(seeded)
    for persona in DEMO_PERSONAS:
        user = await users.get_user(persona.id)
        assert (user.display_name, user.initials, user.role, user.facility_key) == (
            persona.display_name,
            persona.initials,
            persona.role,
            persona.facility_key,
        )
    assert {p.role for p in DEMO_PERSONAS} >= {Role.ADMIN, Role.STAFF_NURSE, Role.HEAD_NURSE}


@pytest.mark.asyncio
async def test_seed_keeps_an_admins_facility_edit(seeded: AsyncEngine) -> None:
    facilities = PgFacilityRepository(seeded, CLOCK)
    current = await facilities.get_facility("ph-demo")
    admin = next(p for p in DEMO_PERSONAS if p.role is Role.ADMIN)
    settings = current.profile.model_copy(update={"name": "Renamed by the admin"})
    await facilities.update_facility("ph-demo", settings, 1, admin.id)
    await seed(seeded, CLOCK)
    after = await facilities.get_facility("ph-demo")
    assert (after.profile.name, after.version) == ("Renamed by the admin", 2)
    assert [s.code for s in after.profile.shifts] == [s.code for s in current.profile.shifts]


@pytest.mark.asyncio
async def test_seed_patient_counts_wards_and_synthetic_marks(seeded: AsyncEngine) -> None:
    patients = PgPatientRepository(seeded, CLOCK)
    ph = await patients.list_patients("ph-demo")
    us = await patients.list_patients("us-demo")
    assert len(ph) == 12
    assert len({p.ward for p in ph}) == 2
    assert {p.ward for p in us} == {"Med-Surg"}
    assert len(us) == 4
    async with seeded.begin() as conn:
        flags = (await conn.execute(select(tables.patient.c.synthetic))).scalars().all()
    assert len(flags) == 16
    assert all(flags)


@pytest.mark.asyncio
async def test_seed_display_names_run_in_order_from_the_demo_cases(seeded: AsyncEngine) -> None:
    letters = {
        case.display_name.removeprefix("Demo patient "): case.patient_id
        for case in load_demo_cases()
    }
    assert sorted(letters) == ["A", "B", "C"]
    patients = PgPatientRepository(seeded, CLOCK)
    names: dict[str, str] = {}
    for key in ("ph-demo", "us-demo"):
        for summary in await patients.list_patients(key):
            names[summary.display_name] = key
    assert sorted(names) == [f"Demo patient {c}" for c in "ABCDEFGHIJKLMNOP"]
    # PH patients take the letters first, then the US ones.
    ph_letters = sorted(n[-1] for n, key in names.items() if key == "ph-demo" and n[-1] != "C")
    us_letters = sorted(n[-1] for n, key in names.items() if key == "us-demo" and n[-1] != "C")
    assert max(ph_letters) < min(us_letters)


@pytest.mark.asyncio
async def test_seed_record_numbers_and_rooms_are_invented_in_one_format(
    seeded: AsyncEngine,
) -> None:
    ph = await all_for(seeded, "ph-demo")
    us = await all_for(seeded, "us-demo")
    assert sorted(r.identity.record_number for r in ph) == [f"SYN-PH-{n:04d}" for n in range(1, 13)]
    assert sorted(r.identity.record_number for r in us) == [f"SYN-US-{n:04d}" for n in range(1, 5)]
    assert all(re.fullmatch(r"\d{3}-[A-B]", r.summary.bed_label) for r in us)
    assert all(r.summary.bed_label.isdigit() for r in ph)


async def all_for(engine: AsyncEngine, facility_key: str) -> list[PatientRecord]:
    patients = PgPatientRepository(engine, CLOCK)
    return [await patients.get_patient(s.id) for s in await patients.list_patients(facility_key)]


@pytest.mark.asyncio
async def test_ph_patient_with_no_allergy_record(seeded: AsyncEngine) -> None:
    found = await record(seeded, "ph-demo", "SYN-PH-0001")
    assert found.context.allergies is None
    assert not found.context.allergies_recorded


@pytest.mark.asyncio
async def test_ph_patient_who_is_dnr(seeded: AsyncEngine) -> None:
    found = await record(seeded, "ph-demo", "SYN-PH-0002")
    assert found.context.code_status.startswith("DNR")


@pytest.mark.asyncio
async def test_ph_patient_who_is_deteriorating(seeded: AsyncEngine) -> None:
    found = await record(seeded, "ph-demo", "SYN-PH-0003")
    vitals = found.context.latest_vitals
    assert vitals is not None
    assert vitals.temperature is not None
    assert vitals.temperature.unit is found.facility.units.temperature
    assert vitals.temperature.value >= Decimal("38.5")
    assert vitals.bp_systolic is not None
    assert vitals.bp_systolic.unit is Ucum.MM_HG
    assert vitals.bp_systolic.value <= 90
    assert vitals.pulse is not None
    assert vitals.pulse.unit is Ucum.PER_MIN
    assert vitals.pulse.value >= 120
    assert vitals.resp_rate is not None
    assert vitals.resp_rate.unit is Ucum.PER_MIN
    assert vitals.resp_rate.value >= 24
    assert vitals.spo2 is not None
    assert vitals.spo2.unit is Ucum.PERCENT
    assert vitals.spo2.value <= 90


@pytest.mark.asyncio
async def test_us_patient_aged_91(seeded: AsyncEngine) -> None:
    found = await record(seeded, "us-demo", "SYN-US-0001")
    assert found.summary.age == 91


@pytest.mark.asyncio
async def test_us_patient_with_no_allergy_record(seeded: AsyncEngine) -> None:
    found = await record(seeded, "us-demo", "SYN-US-0002")
    assert found.context.allergies is None


@pytest.mark.asyncio
async def test_us_patient_at_high_fall_risk(seeded: AsyncEngine) -> None:
    found = await record(seeded, "us-demo", "SYN-US-0003")
    assert found.context.fall_risk is not None
    assert found.context.fall_risk.high


@pytest.mark.asyncio
async def test_us_patient_with_relatives_in_the_record(seeded: AsyncEngine) -> None:
    found = await record(seeded, "us-demo", "SYN-US-0001")
    assert [r.relation for r in found.identity.relatives] == ["spouse", "son"]
    demo = await record(seeded, "us-demo", "SYN-US-0004")
    assert len(demo.identity.relatives) == 1


@pytest.mark.asyncio
async def test_us_vitals_use_the_facilitys_units(seeded: AsyncEngine) -> None:
    for found in await all_for(seeded, "us-demo"):
        vitals = found.context.latest_vitals
        if vitals and vitals.temperature:
            assert vitals.temperature.unit is Ucum.DEG_F
            assert Decimal("90") < vitals.temperature.value < Decimal("110")
        if vitals and vitals.weight:
            assert vitals.weight.unit is found.facility.units.weight


@pytest.mark.asyncio
async def test_seed_command_seeds_the_database_in_database_url(
    database_url: str, engine: AsyncEngine
) -> None:
    done = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "nursing_core.storage.seed"],
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        check=False,
    )
    assert done.returncode == 0
    assert (await counts(engine))["patient"] == 16


def test_seed_command_needs_database_url() -> None:
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    done = subprocess.run(
        [sys.executable, "-m", "nursing_core.storage.seed"],
        env=env,
        capture_output=True,
        check=False,
    )
    assert done.returncode != 0
    assert b"DATABASE_URL" in done.stderr
