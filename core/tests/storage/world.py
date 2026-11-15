"""A few synthetic rows for the repository tests (the real seed comes later).

Core inserts only: a facility with its shifts, a ward, a bed, a patient with an open encounter and
a context, and the demo nurse. Every person here is a demo case or a demo persona.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from nursing_core.demo import DEMO_FACILITIES, DEMO_PERSONAS, DemoCase, load_demo_cases
from nursing_core.domain.facility import FacilityProfile
from nursing_core.domain.notes import (
    FdarDraft,
    GenerationInfo,
    LineReview,
    LineStatus,
    Note,
    NoteStatus,
    RoughNote,
)
from nursing_core.domain.users import Role
from nursing_core.storage import tables
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncEngine

NOW = datetime(2026, 11, 12, 8, 0, tzinfo=UTC)


@dataclass(frozen=True)
class World:
    case: DemoCase
    profile: FacilityProfile
    facility_id: UUID
    ward_id: UUID
    nurse_id: UUID
    admin_id: UUID
    patient_id: UUID
    encounter_id: UUID


def generation() -> GenerationInfo:
    return GenerationInfo(
        provider="fake",
        model="fake-model",
        prompt_version="fdar-test",
        input_tokens=120,
        output_tokens=80,
        cost_usd=Decimal("0.012345"),
        latency_ms=5,
    )


def _facility_values(profile: FacilityProfile, facility_id: UUID) -> dict[str, object]:
    return {
        "id": facility_id,
        "key": profile.key,
        "name": profile.name,
        "timezone": profile.timezone,
        "locale": profile.locale.value,
        "day_starts_at": profile.day_starts_at,
        "note_formats": [f.value for f in profile.note_formats],
        "default_note_format": profile.default_note_format.value,
        "unit_temperature": profile.units.temperature.value,
        "unit_weight": profile.units.weight.value if profile.units.weight else None,
        "unit_volume": profile.units.volume.value,
        "clock": profile.clock,
        "version": 1,
        "updated_by": None,
        "updated_at": NOW,
    }


async def add_patient(
    engine: AsyncEngine,
    world: World,
    *,
    display_name: str,
    ward: str,
    bed_label: str,
    record_number: str,
) -> tuple[UUID, UUID]:
    """Another patient on an open encounter here; returns (patient id, encounter id)."""
    identity = world.case.patient
    patient_id, encounter_id, bed_id = uuid4(), uuid4(), uuid4()
    async with engine.begin() as conn:
        ward_id = world.ward_id
        if ward != world.case.ward:
            ward_id = uuid4()
            await conn.execute(
                insert(tables.ward).values(id=ward_id, facility_id=world.facility_id, name=ward)
            )
        await conn.execute(insert(tables.bed).values(id=bed_id, ward_id=ward_id, label=bed_label))
        await conn.execute(
            insert(tables.patient).values(
                id=patient_id,
                facility_id=world.facility_id,
                display_name=display_name,
                sex=world.case.sex,
                birth_date=identity.birth_date,
                given_name=identity.given_name,
                middle_name=identity.middle_name,
                family_name=identity.family_name,
                suffix=identity.suffix,
                nicknames=identity.nicknames,
                record_number=record_number,
                address=identity.address,
                postal_code=identity.postal_code,
            )
        )
        await conn.execute(
            insert(tables.encounter).values(
                id=encounter_id, patient_id=patient_id, bed_id=bed_id, admitted_at=NOW
            )
        )
        await conn.execute(
            insert(tables.patient_context).values(
                encounter_id=encounter_id,
                context=world.case.context.model_dump(mode="json"),
                updated_at=NOW,
            )
        )
    return patient_id, encounter_id


async def build_world(engine: AsyncEngine) -> World:
    """The PH demo facility, demo case 1's patient on an open encounter, a nurse and the admin."""
    case = load_demo_cases()[0]
    profile = next(f for f in DEMO_FACILITIES if f.key == case.facility_key)
    nurse = next(p for p in DEMO_PERSONAS if p.role is Role.STAFF_NURSE and p.facility_key)
    admin = next(p for p in DEMO_PERSONAS if p.role is Role.ADMIN)
    facility_id, ward_id, bed_id = uuid4(), uuid4(), uuid4()
    identity = case.patient
    async with engine.begin() as conn:
        await conn.execute(insert(tables.facility).values(**_facility_values(profile, facility_id)))
        await conn.execute(
            insert(tables.facility_change).values(
                id=uuid4(),
                facility_id=facility_id,
                version=1,
                changed_by=None,
                changed_at=NOW,
                settings=profile.model_dump(mode="json", exclude={"key"}),
            )
        )
        await conn.execute(
            insert(tables.shift_definition),
            [
                {
                    "facility_id": facility_id,
                    "position": position,
                    "code": shift.code,
                    "label": shift.label,
                    "starts_local": shift.starts_local,
                    "ends_local": shift.ends_local,
                    "ink": shift.ink.value,
                }
                for position, shift in enumerate(profile.shifts)
            ],
        )
        await conn.execute(
            insert(tables.app_user),
            [
                {
                    "id": nurse.id,
                    "display_name": nurse.display_name,
                    "initials": nurse.initials,
                    "role": nurse.role.value,
                    "facility_id": facility_id,
                },
                {
                    "id": admin.id,
                    "display_name": admin.display_name,
                    "initials": admin.initials,
                    "role": admin.role.value,
                    "facility_id": None,
                },
            ],
        )
        await conn.execute(
            insert(tables.ward).values(id=ward_id, facility_id=facility_id, name=case.ward)
        )
        await conn.execute(
            insert(tables.bed).values(id=bed_id, ward_id=ward_id, label=case.bed_label)
        )
        await conn.execute(
            insert(tables.patient).values(
                id=case.patient_id,
                facility_id=facility_id,
                display_name=case.display_name,
                sex=case.sex,
                birth_date=identity.birth_date,
                given_name=identity.given_name,
                middle_name=identity.middle_name,
                family_name=identity.family_name,
                suffix=identity.suffix,
                nicknames=identity.nicknames,
                record_number=identity.record_number,
                address=identity.address,
                postal_code=identity.postal_code,
            )
        )
        if identity.relatives:
            await conn.execute(
                insert(tables.patient_relative),
                [
                    {
                        "patient_id": case.patient_id,
                        "position": position,
                        "name": relative.name,
                        "relation": relative.relation,
                    }
                    for position, relative in enumerate(identity.relatives)
                ],
            )
        await conn.execute(
            insert(tables.encounter).values(
                id=case.rough_note.encounter_id,
                patient_id=case.patient_id,
                bed_id=bed_id,
                admitted_at=NOW,
            )
        )
        await conn.execute(
            insert(tables.patient_context).values(
                encounter_id=case.rough_note.encounter_id,
                context=case.context.model_dump(mode="json"),
                updated_at=NOW,
            )
        )
    return World(
        case=case,
        profile=profile,
        facility_id=facility_id,
        ward_id=ward_id,
        nurse_id=nurse.id,
        admin_id=admin.id,
        patient_id=case.patient_id,
        encounter_id=case.rough_note.encounter_id,
    )


def rough_note(world: World, **changes: object) -> RoughNote:
    """A fresh rough note (new id) from the demo case; pass fields to change."""
    return world.case.rough_note.model_copy(update={"id": uuid4(), **changes})


def draft_note(rough: RoughNote, world: World) -> Note:
    """The demo case's expected draft, as the note the worker would save for this rough note."""
    return Note(
        id=uuid4(),
        rough_note_id=rough.id,
        encounter_id=rough.encounter_id,
        status=NoteStatus.DRAFT,
        version=1,
        draft=world.case.expected_draft,
        checklist=world.case.expected_checklist,
        generation=generation(),
        signature=None,
        discard=None,
    )


def confirmed(draft: FdarDraft) -> FdarDraft:
    """The draft with every line that needed the nurse confirmed, so it can be signed."""
    data = draft.model_dump()
    for entry in data["entries"]:
        for line in [entry["focus"], *entry["data"], *entry["action"], *entry["response"]]:
            if (
                line["status"] is not LineStatus.SOURCE_FOUND
                and line["review"] is LineReview.PENDING
            ):
                line["review"] = LineReview.CONFIRMED
    return FdarDraft.model_validate(data)
