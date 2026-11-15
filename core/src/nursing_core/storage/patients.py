"""The patient repository: each patient on their open encounter, with identity and context."""

from datetime import date
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from nursing_core.domain.errors import NotFound
from nursing_core.domain.patient import (
    PatientContext,
    PatientIdentity,
    PatientRecord,
    PatientSummary,
    Relative,
)
from nursing_core.ports import Clock
from nursing_core.storage import tables
from nursing_core.storage.facilities import load_facilities
from nursing_core.storage.rows import AnyRow

_PATIENT = tables.patient
_ENCOUNTER = tables.encounter
_BED = tables.bed
_WARD = tables.ward
_FACILITY = tables.facility

_STAY = (
    _PATIENT.join(_ENCOUNTER, _ENCOUNTER.c.patient_id == _PATIENT.c.id)
    .join(_BED, _BED.c.id == _ENCOUNTER.c.bed_id)
    .join(_WARD, _WARD.c.id == _BED.c.ward_id)
    .join(_FACILITY, _FACILITY.c.id == _PATIENT.c.facility_id)
)


def _age(born: date, today: date) -> int:
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


class PgPatientRepository:
    def __init__(self, engine: AsyncEngine, clock: Clock) -> None:
        self._engine = engine
        self._clock = clock

    def _summary(self, row: AnyRow) -> PatientSummary:
        today = self._clock.now().astimezone(ZoneInfo(row.timezone)).date()
        return PatientSummary(
            id=row.id,
            display_name=row.display_name,
            age=_age(row.birth_date, today),
            sex=row.sex,
            ward=row.ward_name,
            bed_label=row.bed_label,
            facility_key=row.facility_key,
        )

    async def list_patients(self, facility_key: str) -> list[PatientSummary]:
        """Patients on an open encounter, by ward, then bed, then display name."""
        async with self._engine.begin() as conn:
            rows = (
                await conn.execute(
                    select(
                        _PATIENT.c.id,
                        _PATIENT.c.display_name,
                        _PATIENT.c.birth_date,
                        _PATIENT.c.sex,
                        _WARD.c.name.label("ward_name"),
                        _BED.c.label.label("bed_label"),
                        _FACILITY.c.key.label("facility_key"),
                        _FACILITY.c.timezone,
                    )
                    .select_from(_STAY)
                    .where(_FACILITY.c.key == facility_key, _ENCOUNTER.c.discharged_at.is_(None))
                    .order_by(_WARD.c.name, _BED.c.label, _PATIENT.c.display_name)
                )
            ).all()
        return [self._summary(row) for row in rows]

    async def get_patient(self, patient_id: UUID) -> PatientRecord:
        """The patient's open encounter. Raises NotFound for a patient with none."""
        return await self._record(_PATIENT.c.id == patient_id, _ENCOUNTER.c.discharged_at.is_(None))

    async def get_patient_by_encounter(self, encounter_id: UUID) -> PatientRecord:
        return await self._record(_ENCOUNTER.c.id == encounter_id)

    async def _record(self, *conditions: ColumnElement[bool]) -> PatientRecord:
        async with self._engine.begin() as conn:
            return await self._load(conn, *conditions)

    async def _load(self, conn: AsyncConnection, *conditions: ColumnElement[bool]) -> PatientRecord:
        row = (
            await conn.execute(
                select(
                    _PATIENT,
                    _ENCOUNTER.c.id.label("encounter_id"),
                    _WARD.c.name.label("ward_name"),
                    _BED.c.label.label("bed_label"),
                    _FACILITY.c.key.label("facility_key"),
                    _FACILITY.c.timezone,
                    tables.patient_context.c.context,
                )
                .select_from(
                    _STAY.join(
                        tables.patient_context,
                        tables.patient_context.c.encounter_id == _ENCOUNTER.c.id,
                    )
                )
                .where(*conditions)
            )
        ).one_or_none()
        if row is None:
            raise NotFound("no such patient")
        relatives = (
            await conn.execute(
                select(tables.patient_relative.c.name, tables.patient_relative.c.relation)
                .where(tables.patient_relative.c.patient_id == row.id)
                .order_by(tables.patient_relative.c.position)
            )
        ).all()
        facility = (await load_facilities(conn, _FACILITY.c.id == row.facility_id))[0]
        return PatientRecord(
            summary=self._summary(row),
            encounter_id=row.encounter_id,
            identity=PatientIdentity(
                given_name=row.given_name,
                middle_name=row.middle_name,
                family_name=row.family_name,
                suffix=row.suffix,
                nicknames=list(row.nicknames),
                relatives=[Relative(name=r.name, relation=r.relation) for r in relatives],
                record_number=row.record_number,
                birth_date=row.birth_date,
                address=row.address,
                postal_code=row.postal_code,
            ),
            context=PatientContext.model_validate(row.context),
            facility=facility.profile,
        )
