"""The synthetic seed: two demo facilities, their staff and their patients.

Everything here is invented and marked synthetic. The seed is safe to run again and again: each
row has a fixed id (the demo cases' own, or one made from a fixed namespace and a label), every
insert is `ON CONFLICT DO NOTHING`, and nothing depends on the clock except the `updated_at` and
`changed_at` stamps. So a second run adds nothing, and never undoes an admin's edit to a facility
or a chart imported since. It writes no rough notes, jobs or notes: the nurse types the note.

Names come from Faker, one instance per facility with a fixed seed and the facility's locale,
generated in a fixed order, so every database gets the same patients. Run it with
`python -m nursing_core.storage.seed` against `DATABASE_URL`.
"""

import asyncio
import os
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from faker import Faker
from sqlalchemy import Table
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from nursing_core.clock import SystemClock
from nursing_core.db import create_engine
from nursing_core.demo import DEMO_FACILITIES, DEMO_PERSONAS, DemoCase, load_demo_cases
from nursing_core.domain.facility import FacilityProfile
from nursing_core.domain.patient import (
    FallRisk,
    LineOrTube,
    MedicineDue,
    PatientContext,
    PatientIdentity,
    PendingTest,
    Relative,
    Vitals,
)
from nursing_core.domain.units import Quantity, Ucum
from nursing_core.ports import Clock
from nursing_core.storage import tables
from nursing_core.storage.rows import facility_columns, shift_rows

NAMESPACE = UUID("5eed0000-0000-4000-8000-00000000d3a0")
# The demo night is 2026-11-11 to 2026-11-12; stays begin a day or two before it.
ADMITTED = datetime(2026, 11, 10, 6, 0, tzinfo=UTC)
DEMO_DAY = date(2026, 11, 12)
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


@dataclass(frozen=True)
class Extra:
    """One invented patient beyond the demo cases. `edge` marks the ones tests look for."""

    number: int  # the record number's counter: SYN-PH-0003 is number 3
    ward: str
    bed: str
    born: date
    edge: str | None = None


@dataclass(frozen=True)
class FacilityPlan:
    locale: str
    faker_seed: int
    record_prefix: str
    extras: list[Extra]


# Record numbers 7 and 12 (PH) and 4 (US) belong to the demo cases, so they are skipped here.
PLANS: dict[str, FacilityPlan] = {
    "ph-demo": FacilityPlan(
        locale="en_PH",
        faker_seed=20261111,
        record_prefix="SYN-PH-",
        extras=[
            Extra(1, "Medical Ward", "1", date(1971, 4, 9), "no_allergy_record"),
            Extra(2, "Medical Ward", "3", date(1949, 9, 23), "dnr"),
            Extra(3, "Medical Ward", "5", date(1958, 1, 30), "deteriorating"),
            Extra(4, "Medical Ward", "9", date(1990, 7, 14)),
            Extra(5, "Medical Ward", "10", date(1983, 12, 2)),
            Extra(6, "Surgical Ward", "2", date(1976, 5, 21)),
            Extra(8, "Surgical Ward", "4", date(1955, 10, 8)),
            Extra(9, "Surgical Ward", "6", date(2001, 3, 17)),
            Extra(10, "Surgical Ward", "8", date(1968, 8, 28)),
            Extra(11, "Surgical Ward", "11", date(1939, 11, 30)),
        ],
    ),
    "us-demo": FacilityPlan(
        locale="en_US",
        faker_seed=20261112,
        record_prefix="SYN-US-",
        extras=[
            # Born in 1935: 91 on the demo day. Two relatives in the record.
            Extra(1, "Med-Surg", "412-B", date(1935, 6, 15), "aged_91"),
            Extra(2, "Med-Surg", "414-A", date(1962, 2, 3), "no_allergy_record"),
            Extra(3, "Med-Surg", "415-A", date(1951, 8, 19), "high_fall_risk"),
        ],
    ),
}

_ALLERGIES: list[list[str]] = [
    [],
    ["penicillin (rash)"],
    ["sulfa drugs (hives)"],
    ["latex"],
    ["shellfish (hives)"],
]
# (name, dose, route, aliases): common medicines, given at a fixed hour of the demo day.
_MEDICINES: list[tuple[str, str, str, list[str]]] = [
    ("Paracetamol", "500 mg", "PO", ["paracetamol", "acetaminophen"]),
    ("Omeprazole", "40 mg", "IV", ["omeprazole"]),
    ("Enoxaparin", "40 mg", "SUBQ", ["enoxaparin"]),
    ("Metoprolol", "25 mg", "PO", ["metoprolol"]),
]
_TESTS = ["CBC", "BMP", "Urinalysis"]


def _id(*parts: str) -> UUID:
    return uuid5(NAMESPACE, "/".join(parts))


@dataclass(frozen=True)
class Stay:
    """One patient on one open encounter, ready to insert."""

    patient_id: UUID
    encounter_id: UUID
    display_name: str
    sex: str
    ward: str
    bed: str
    identity: PatientIdentity
    context: PatientContext
    admitted_at: datetime


def _temperature(celsius: str, profile: FacilityProfile) -> Quantity:
    """A temperature in the facility's own unit."""
    value = Decimal(celsius)
    if profile.units.temperature is Ucum.DEG_F:
        return Quantity(value=(value * 9 / 5 + 32).quantize(Decimal("0.1")), unit=Ucum.DEG_F)
    return Quantity(value=value, unit=profile.units.temperature)


def _weight(kilograms: int, profile: FacilityProfile) -> Quantity | None:
    """A weight in the facility's own unit; None where the facility has no default weight unit."""
    unit = profile.units.weight
    if unit is None:
        return None
    if unit is Ucum.LB:
        return Quantity(
            value=(Decimal(kilograms) * Decimal("2.2046")).quantize(Decimal("1")), unit=unit
        )
    return Quantity(value=Decimal(kilograms), unit=unit)


def _vitals(profile: FacilityProfile, fake: Faker, *, deteriorating: bool) -> Vitals:
    taken = datetime(2026, 11, 12, 2, 0, tzinfo=ZoneInfo(profile.timezone))

    def number(low: int, high: int, unit: Ucum) -> Quantity:
        return Quantity(value=Decimal(fake.random_int(low, high)), unit=unit)

    if deteriorating:
        return Vitals(
            taken_at=taken,
            temperature=_temperature("38.9", profile),
            pulse=number(124, 134, Ucum.PER_MIN),
            resp_rate=number(26, 30, Ucum.PER_MIN),
            bp_systolic=number(80, 88, Ucum.MM_HG),
            bp_diastolic=number(46, 54, Ucum.MM_HG),
            spo2=number(84, 89, Ucum.PERCENT),
            weight=_weight(fake.random_int(55, 90), profile),
        )
    return Vitals(
        taken_at=taken,
        temperature=_temperature(f"36.{fake.random_int(5, 9)}", profile),
        pulse=number(64, 92, Ucum.PER_MIN),
        resp_rate=number(14, 18, Ucum.PER_MIN),
        bp_systolic=number(108, 134, Ucum.MM_HG),
        bp_diastolic=number(64, 82, Ucum.MM_HG),
        spo2=number(95, 99, Ucum.PERCENT),
        weight=_weight(fake.random_int(48, 95), profile),
    )


def _context(profile: FacilityProfile, fake: Faker, edge: str | None) -> PatientContext:
    zone = ZoneInfo(profile.timezone)
    allergies: list[str] | None = _ALLERGIES[fake.random_int(0, len(_ALLERGIES) - 1)]
    if edge == "no_allergy_record":
        allergies = None
    lines = (
        [LineOrTube(kind="IV line", description="PIV, left forearm", aliases=["PIV", "IV"])]
        if fake.random_int(0, 1)
        else []
    )
    name, dose, route, aliases = _MEDICINES[fake.random_int(0, len(_MEDICINES) - 1)]
    due = MedicineDue(
        name=name,
        dose=dose,
        route=route,
        due_at=datetime(2026, 11, 12, fake.random_int(6, 20), 0, tzinfo=zone),
        aliases=aliases,
    )
    test = _TESTS[fake.random_int(0, len(_TESTS) - 1)]
    pending = PendingTest(
        name=test,
        sent_at=datetime(2026, 11, 12, 1, 30, tzinfo=zone),
        aliases=[test],
    )
    high_fall_risk = edge == "high_fall_risk"
    score = fake.random_int(55, 70) if high_fall_risk else fake.random_int(10, 40)
    return PatientContext(
        allergies=allergies,
        code_status="DNR" if edge == "dnr" else "Full code",
        lines_tubes=lines,
        medicines_due=[due],
        pending_tests=[pending],
        latest_vitals=_vitals(profile, fake, deteriorating=edge == "deteriorating"),
        fall_risk=FallRisk(scale="Morse", score=score, high=score >= 45),
    )


def _extra_stay(
    profile: FacilityProfile, plan: FacilityPlan, fake: Faker, extra: Extra, display_name: str
) -> Stay:
    sex = fake.random_element(("F", "M"))
    given = fake.first_name_female() if sex == "F" else fake.first_name_male()
    family = fake.last_name()
    identity = PatientIdentity(
        given_name=given,
        middle_name=None,
        family_name=family,
        suffix=None,
        nicknames=[],
        relatives=(
            [
                Relative(name=f"{fake.first_name_female()} {family}", relation="spouse"),
                Relative(name=f"{fake.first_name_male()} {family}", relation="son"),
            ]
            if extra.edge == "aged_91"
            else []
        ),
        record_number=f"{plan.record_prefix}{extra.number:04d}",
        birth_date=extra.born,
        address=fake.street_address(),
        postal_code=fake.postcode(),
    )
    key = f"{profile.key}/{identity.record_number}"
    return Stay(
        patient_id=_id("patient", key),
        encounter_id=_id("encounter", key),
        display_name=display_name,
        sex=sex,
        ward=extra.ward,
        bed=extra.bed,
        identity=identity,
        context=_context(profile, fake, extra.edge),
        admitted_at=ADMITTED,
    )


def _case_stay(case: DemoCase) -> Stay:
    return Stay(
        patient_id=case.patient_id,
        encounter_id=case.rough_note.encounter_id,
        display_name=case.display_name,
        sex=case.sex,
        ward=case.ward,
        bed=case.bed_label,
        identity=case.patient,
        context=case.context,
        admitted_at=ADMITTED,
    )


def build_stays() -> dict[str, list[Stay]]:
    """Every patient of every demo facility, the demo cases first; the same on every call."""
    cases = load_demo_cases()
    taken = {c.display_name for c in cases}
    free = (f"Demo patient {letter}" for letter in LETTERS if f"Demo patient {letter}" not in taken)
    stays: dict[str, list[Stay]] = {}
    for profile in DEMO_FACILITIES:
        plan = PLANS[profile.key]
        fake = Faker(plan.locale)
        fake.seed_instance(plan.faker_seed)
        stays[profile.key] = [_case_stay(c) for c in cases if c.facility_key == profile.key]
        for extra in plan.extras:
            stays[profile.key].append(_extra_stay(profile, plan, fake, extra, next(free)))
    return stays


async def _add(conn: AsyncConnection, table: Table, rows: list[dict[str, Any]]) -> None:
    """Insert the rows that aren't there yet; a row already present is left exactly as it is."""
    if rows:
        await conn.execute(insert(table).on_conflict_do_nothing(), rows)


async def _add_parents(
    conn: AsyncConnection, table: Table, rows: list[dict[str, Any]]
) -> set[UUID]:
    """Like `_add`, and returns the ids of the rows this call created (not the ones already there).

    A child row (a shift, a relative) is written only for a parent created now: otherwise an
    admin's edit to the children would be topped up with whatever the preset has that they removed.
    """
    created = await conn.execute(
        insert(table).values(rows).on_conflict_do_nothing().returning(table.c.id)
    )
    return set(created.scalars())


async def seed(engine: AsyncEngine, clock: Clock) -> None:
    """Write the demo facilities, staff and patients that are not already there."""
    now = clock.now()
    stays = build_stays()
    facility_ids = {p.key: _id("facility", p.key) for p in DEMO_FACILITIES}
    async with engine.begin() as conn:
        # The facility is written before its users: facility.updated_by points at a user later.
        new_facilities = await _add_parents(
            conn,
            tables.facility,
            [
                {
                    "id": facility_ids[p.key],
                    "key": p.key,
                    **facility_columns(p),
                    "version": 1,
                    "updated_by": None,
                    "updated_at": now,
                }
                for p in DEMO_FACILITIES
            ],
        )
        await _add(
            conn,
            tables.shift_definition,
            [
                row
                for p in DEMO_FACILITIES
                for row in shift_rows(facility_ids[p.key], p.shifts)
                if facility_ids[p.key] in new_facilities
            ],
        )
        await _add(
            conn,
            tables.facility_change,
            [
                {
                    "id": _id("facility-change", p.key, "1"),
                    "facility_id": facility_ids[p.key],
                    "version": 1,
                    "changed_by": None,
                    "changed_at": now,
                    "settings": p.model_dump(mode="json", exclude={"key"}),
                }
                for p in DEMO_FACILITIES
                if facility_ids[p.key] in new_facilities
            ],
        )
        await _add(
            conn,
            tables.app_user,
            [
                {
                    "id": persona.id,
                    "display_name": persona.display_name,
                    "initials": persona.initials,
                    "role": persona.role.value,
                    "persona": True,
                    "facility_id": facility_ids[persona.facility_key]
                    if persona.facility_key
                    else None,
                }
                for persona in DEMO_PERSONAS
            ],
        )
        wards = sorted({(key, s.ward) for key, group in stays.items() for s in group})
        await _add(
            conn,
            tables.ward,
            [
                {"id": _id("ward", key, ward), "facility_id": facility_ids[key], "name": ward}
                for key, ward in wards
            ],
        )
        await _add(
            conn,
            tables.bed,
            [
                {
                    "id": _id("bed", key, s.ward, s.bed),
                    "ward_id": _id("ward", key, s.ward),
                    "label": s.bed,
                }
                for key, group in stays.items()
                for s in group
            ],
        )
        everyone = [(key, s) for key, group in stays.items() for s in group]
        new_patients = await _add_parents(
            conn,
            tables.patient,
            [
                {
                    "id": s.patient_id,
                    "facility_id": facility_ids[key],
                    "display_name": s.display_name,
                    "sex": s.sex,
                    "birth_date": s.identity.birth_date,
                    "given_name": s.identity.given_name,
                    "middle_name": s.identity.middle_name,
                    "family_name": s.identity.family_name,
                    "suffix": s.identity.suffix,
                    "nicknames": s.identity.nicknames,
                    "record_number": s.identity.record_number,
                    "address": s.identity.address,
                    "postal_code": s.identity.postal_code,
                    "synthetic": True,
                }
                for key, s in everyone
            ],
        )
        await _add(
            conn,
            tables.patient_relative,
            [
                {
                    "patient_id": s.patient_id,
                    "position": position,
                    "name": relative.name,
                    "relation": relative.relation,
                }
                for _, s in everyone
                if s.patient_id in new_patients
                for position, relative in enumerate(s.identity.relatives)
            ],
        )
        await _add(
            conn,
            tables.encounter,
            [
                {
                    "id": s.encounter_id,
                    "patient_id": s.patient_id,
                    "bed_id": _id("bed", key, s.ward, s.bed),
                    "admitted_at": s.admitted_at + timedelta(hours=index),
                    "discharged_at": None,
                }
                for index, (key, s) in enumerate(everyone)
                if s.patient_id in new_patients
            ],
        )
        await _add(
            conn,
            tables.patient_context,
            [
                {
                    "encounter_id": s.encounter_id,
                    "context": s.context.model_dump(mode="json"),
                    "updated_at": now,
                }
                for _, s in everyone
                if s.patient_id in new_patients
            ],
        )


def main() -> None:
    """`python -m nursing_core.storage.seed`: seed the database in `DATABASE_URL`."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set")

    async def run() -> None:
        engine = create_engine(url)
        try:
            await seed(engine, SystemClock())
        finally:
            await engine.dispose()

    asyncio.run(run())
    print("seeded the demo facilities")


if __name__ == "__main__":
    main()
