"""The first migration, the tables it creates and the triggers that lock the record."""

import uuid
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from typing import Any, get_args

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from nursing_core.db import create_engine
from nursing_core.domain.facility import FacilitySettings, Locale, NoteFormat, ShiftInk
from nursing_core.domain.jobs import JobFailure, JobStatus
from nursing_core.domain.notes import NoteStatus
from nursing_core.domain.units import TEMPERATURE_UNITS, VOLUME_UNITS, WEIGHT_UNITS, Ucum
from nursing_core.domain.users import Role
from nursing_core.storage import tables
from nursing_core.storage.migrate import upgrade
from nursing_core.storage.testdb import fresh_database
from sqlalchemy import Connection, insert, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

NOW = datetime(2026, 11, 15, 8, 0, tzinfo=UTC)
HASH = "a" * 64


def _id() -> uuid.UUID:
    return uuid.uuid4()


async def _build_world(engine: AsyncEngine) -> dict[str, uuid.UUID]:
    """One synthetic facility with a nurse, a patient, an encounter and a rough note."""
    ids = {
        name: _id()
        for name in ("facility", "nurse", "ward", "bed", "patient", "encounter", "rough_note")
    }
    async with engine.begin() as conn:
        await conn.execute(
            insert(tables.facility).values(
                id=ids["facility"],
                key="demo-a",
                name="SYNTHETIC Demo Hospital A",
                timezone="Asia/Manila",
                locale=Locale.EN_PH,
                day_starts_at=time(6),
                note_formats=[NoteFormat.FDAR],
                default_note_format=NoteFormat.FDAR,
                unit_temperature=Ucum.CEL,
                unit_weight=Ucum.KG,
                unit_volume=Ucum.ML,
                clock="24h",
                version=1,
                updated_at=NOW,
            )
        )
        await conn.execute(
            insert(tables.app_user).values(
                id=ids["nurse"],
                display_name="Demo Nurse",
                initials="DN",
                role=Role.STAFF_NURSE,
                facility_id=ids["facility"],
            )
        )
        await conn.execute(
            insert(tables.ward).values(id=ids["ward"], facility_id=ids["facility"], name="Ward 1")
        )
        await conn.execute(
            insert(tables.bed).values(id=ids["bed"], ward_id=ids["ward"], label="1A")
        )
        await conn.execute(
            insert(tables.patient).values(
                id=ids["patient"],
                facility_id=ids["facility"],
                display_name="Demo patient A",
                sex="female",
                birth_date=date(1950, 1, 1),
                given_name="Demo",
                family_name="Patient",
                nicknames=[],
                record_number="REC-0001",
            )
        )
        await conn.execute(
            insert(tables.encounter).values(
                id=ids["encounter"],
                patient_id=ids["patient"],
                bed_id=ids["bed"],
                admitted_at=NOW - timedelta(days=2),
            )
        )
        await conn.execute(
            insert(tables.rough_note).values(
                id=ids["rough_note"],
                encounter_id=ids["encounter"],
                author_id=ids["nurse"],
                text="BP 120/80, resting",
                written_at=NOW,
                note_format=NoteFormat.FDAR,
                shift_code="6-2",
                shift_label="6-2",
                shift_starts_at=NOW - timedelta(hours=2),
                shift_ends_at=NOW + timedelta(hours=6),
                shift_date=date(2026, 11, 15),
                shift_timezone="Asia/Manila",
                idempotency_key="key-1",
                body_hash=HASH,
            )
        )
    return ids


def _note_values(ids: dict[str, uuid.UUID]) -> dict[str, Any]:
    return {
        "id": _id(),
        "rough_note_id": ids["rough_note"],
        "encounter_id": ids["encounter"],
        "status": NoteStatus.DRAFT,
        "version": 1,
        "draft": {},
        "checklist": [],
        "generation": {},
        "created_at": NOW,
        "updated_at": NOW,
    }


def _version_values(note_id: uuid.UUID, ids: dict[str, uuid.UUID]) -> dict[str, Any]:
    """The record of a note signed at version 2 by the nurse at NOW with HASH."""
    return {
        "id": _id(),
        "note_id": note_id,
        "version": 2,
        "content": {"text": "signed"},
        "content_hash": HASH,
        "signed_by": ids["nurse"],
        "signed_at": NOW,
    }


async def _sign(conn: AsyncConnection, note_id: uuid.UUID, ids: dict[str, uuid.UUID]) -> None:
    await conn.execute(
        update(tables.note)
        .where(tables.note.c.id == note_id)
        .values(
            status=NoteStatus.SIGNED,
            version=2,
            signed_by=ids["nurse"],
            signed_at=NOW,
            content_hash=HASH,
        )
    )


async def _signed_note(engine: AsyncEngine) -> tuple[uuid.UUID, uuid.UUID, dict[str, uuid.UUID]]:
    """A signed note with its signed version: returns (note id, version id, world ids).

    As `sign()` does, the note is signed first and its version written in the same transaction.
    """
    ids = await _build_world(engine)
    note = _note_values(ids)
    version = _version_values(note["id"], ids)
    async with engine.begin() as conn:
        await conn.execute(insert(tables.note).values(note))
        await _sign(conn, note["id"], ids)
        await conn.execute(insert(tables.note_version).values(version))
    return note["id"], version["id"], ids


def _sqlstate(raised: pytest.ExceptionInfo[DBAPIError]) -> object:
    return getattr(raised.value.orig, "sqlstate", None)


def _discarded(ids: dict[str, uuid.UUID]) -> dict[str, Any]:
    return _note_values(ids) | {
        "status": NoteStatus.DISCARDED,
        "discarded_by": ids["nurse"],
        "discarded_at": NOW,
    }


@pytest.mark.asyncio
async def test_migration_upgrades_an_empty_database(postgres_url: str) -> None:
    async with fresh_database(postgres_url, "template1") as url:
        await upgrade(url)
        engine = create_engine(url)
        try:
            async with engine.connect() as conn:
                rows = await conn.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                )
                found = {row[0] for row in rows}
        finally:
            await engine.dispose()
    assert set(tables.metadata.tables) <= found
    assert "alembic_version" in found


@pytest.mark.asyncio
async def test_upgrade_twice_changes_nothing(database_url: str) -> None:
    await upgrade(database_url)


@pytest.mark.asyncio
async def test_migrated_schema_matches_the_table_definitions(engine: AsyncEngine) -> None:
    def not_the_version_table(
        _obj: object, name: str | None, kind: str, _reflected: bool, _other: object
    ) -> bool:
        return not (kind == "table" and name == "alembic_version")

    def differences(conn: Connection) -> list[Any]:
        context = MigrationContext.configure(
            conn, opts={"compare_type": True, "include_object": not_the_version_table}
        )
        return compare_metadata(context, tables.metadata)

    async with engine.connect() as conn:
        assert await conn.run_sync(differences) == []


@pytest.mark.asyncio
async def test_database_refuses_update_of_a_signed_version(engine: AsyncEngine) -> None:
    _, version_id, _ = await _signed_note(engine)
    with pytest.raises(DBAPIError, match=r"note_version.*not allowed"):
        async with engine.begin() as conn:
            await conn.execute(
                update(tables.note_version)
                .where(tables.note_version.c.id == version_id)
                .values(content={"text": "changed"})
            )


@pytest.mark.asyncio
async def test_database_refuses_delete_of_a_signed_version(engine: AsyncEngine) -> None:
    _, version_id, _ = await _signed_note(engine)
    with pytest.raises(DBAPIError, match=r"note_version.*not allowed"):
        async with engine.begin() as conn:
            await conn.execute(
                tables.note_version.delete().where(tables.note_version.c.id == version_id)
            )


@pytest.mark.asyncio
async def test_database_refuses_changing_a_signed_note(engine: AsyncEngine) -> None:
    note_id, _, _ = await _signed_note(engine)
    with pytest.raises(DBAPIError, match=r"note.*not allowed"):
        async with engine.begin() as conn:
            await conn.execute(
                update(tables.note).where(tables.note.c.id == note_id).values(draft={"x": 1})
            )
    with pytest.raises(DBAPIError, match=r"note.*not allowed"):
        async with engine.begin() as conn:
            await conn.execute(tables.note.delete().where(tables.note.c.id == note_id))


@pytest.mark.asyncio
async def test_database_refuses_a_version_for_a_draft_note(engine: AsyncEngine) -> None:
    ids = await _build_world(engine)
    note = _note_values(ids)
    async with engine.begin() as conn:
        await conn.execute(insert(tables.note).values(note))
    with pytest.raises(DBAPIError, match=r"note_version.*INSERT not allowed") as raised:
        async with engine.begin() as conn:
            await conn.execute(
                insert(tables.note_version).values(
                    _version_values(note["id"], ids) | {"version": 1}
                )
            )
    assert _sqlstate(raised) == "23001"


@pytest.mark.asyncio
async def test_database_refuses_a_version_for_a_discarded_note(engine: AsyncEngine) -> None:
    ids = await _build_world(engine)
    note = _discarded(ids)
    async with engine.begin() as conn:
        await conn.execute(insert(tables.note).values(note))
    with pytest.raises(DBAPIError, match=r"note_version.*INSERT not allowed") as raised:
        async with engine.begin() as conn:
            await conn.execute(
                insert(tables.note_version).values(
                    _version_values(note["id"], ids) | {"version": 1}
                )
            )
    assert _sqlstate(raised) == "23001"


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["content_hash", "signed_by", "signed_at", "version"])
async def test_database_refuses_a_version_whose_hash_signer_time_or_version_is_not_the_notes(
    engine: AsyncEngine, field: str
) -> None:
    ids = await _build_world(engine)
    note = _note_values(ids)
    other_nurse = _id()
    async with engine.begin() as conn:
        await conn.execute(
            insert(tables.app_user).values(
                id=other_nurse,
                display_name="Other Demo Nurse",
                initials="OD",
                role=Role.STAFF_NURSE,
                facility_id=ids["facility"],
            )
        )
        await conn.execute(insert(tables.note).values(note))
        await _sign(conn, note["id"], ids)
    wrong = {
        "content_hash": "b" * 64,
        "signed_by": other_nurse,
        "signed_at": NOW + timedelta(seconds=1),
        "version": 3,
    }[field]
    with pytest.raises(DBAPIError, match=r"note_version.*INSERT not allowed") as raised:
        async with engine.begin() as conn:
            await conn.execute(
                insert(tables.note_version).values(
                    _version_values(note["id"], ids) | {field: wrong}
                )
            )
    assert _sqlstate(raised) == "23001"
    async with engine.begin() as conn:  # the note's own version is still taken
        await conn.execute(insert(tables.note_version).values(_version_values(note["id"], ids)))


@pytest.mark.asyncio
async def test_database_refuses_reopening_a_discarded_note(engine: AsyncEngine) -> None:
    ids = await _build_world(engine)
    note = _discarded(ids)
    async with engine.begin() as conn:
        await conn.execute(insert(tables.note).values(note))
    reopen = (
        update(tables.note)
        .where(tables.note.c.id == note["id"])
        .values(status=NoteStatus.DRAFT, discarded_by=None, discarded_at=None)
    )
    change = update(tables.note).where(tables.note.c.id == note["id"]).values(draft={"x": 1})
    delete = tables.note.delete().where(tables.note.c.id == note["id"])
    for statement, action in ((reopen, "UPDATE"), (change, "UPDATE"), (delete, "DELETE")):
        with pytest.raises(DBAPIError, match=rf"note.*discarded.*{action} not allowed") as raised:
            async with engine.begin() as conn:
                await conn.execute(statement)
        assert _sqlstate(raised) == "23001"


@pytest.mark.asyncio
async def test_database_refuses_changing_a_rough_note(engine: AsyncEngine) -> None:
    ids = await _build_world(engine)
    rough = tables.rough_note
    for statement, action in (
        (update(rough).where(rough.c.id == ids["rough_note"]).values(text="changed"), "UPDATE"),
        (rough.delete().where(rough.c.id == ids["rough_note"]), "DELETE"),
        (text("TRUNCATE rough_note CASCADE"), "TRUNCATE"),
    ):
        with pytest.raises(DBAPIError, match=rf"rough_note.*{action} not allowed") as raised:
            async with engine.begin() as conn:
                await conn.execute(statement)
        assert _sqlstate(raised) == "23001"


@pytest.mark.asyncio
async def test_the_record_guards_apply_to_a_database_that_already_holds_notes(
    postgres_url: str,
) -> None:
    # `make up` on a local database at 0001: the new guards check new writes, not old rows.
    async with fresh_database(postgres_url, "template1") as url:
        await upgrade(url, "0001")
        engine = create_engine(url)
        try:
            ids = await _build_world(engine)
            note = _note_values(ids)
            async with engine.begin() as conn:
                await conn.execute(insert(tables.note).values(note))
                # At 0001 a version could be written for a draft: an old row the upgrade keeps.
                await conn.execute(
                    insert(tables.note_version).values(_version_values(note["id"], ids))
                )
            await upgrade(url)
            async with engine.connect() as conn:
                head = (await conn.execute(text("SELECT version_num FROM alembic_version"))).one()
                kept = (await conn.execute(text("SELECT count(*) FROM note_version"))).scalar_one()
            assert (head[0], kept) == ("0002", 1)
            with pytest.raises(DBAPIError, match=r"rough_note.*UPDATE not allowed"):
                async with engine.begin() as conn:
                    await conn.execute(update(tables.rough_note).values(text="changed"))
        finally:
            await engine.dispose()


@pytest.mark.asyncio
async def test_a_draft_note_can_still_be_updated_and_deleted(engine: AsyncEngine) -> None:
    ids = await _build_world(engine)
    values = _note_values(ids)
    async with engine.begin() as conn:
        await conn.execute(insert(tables.note).values(values))
        await conn.execute(
            update(tables.note).where(tables.note.c.id == values["id"]).values(draft={"x": 1})
        )
        await conn.execute(tables.note.delete().where(tables.note.c.id == values["id"]))
        remaining = (await conn.execute(text("SELECT count(*) FROM note"))).scalar_one()
    assert remaining == 0


@pytest.mark.asyncio
async def test_database_refuses_changing_facility_history(engine: AsyncEngine) -> None:
    ids = await _build_world(engine)
    change_id = _id()
    async with engine.begin() as conn:
        await conn.execute(
            insert(tables.facility_change).values(
                id=change_id,
                facility_id=ids["facility"],
                version=1,
                changed_by=None,
                changed_at=NOW,
                settings={"name": "SYNTHETIC Demo Hospital A"},
            )
        )
    with pytest.raises(DBAPIError, match=r"facility_change.*not allowed"):
        async with engine.begin() as conn:
            await conn.execute(
                update(tables.facility_change)
                .where(tables.facility_change.c.id == change_id)
                .values(settings={})
            )
    with pytest.raises(DBAPIError, match=r"facility_change.*not allowed"):
        async with engine.begin() as conn:
            await conn.execute(
                tables.facility_change.delete().where(tables.facility_change.c.id == change_id)
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("table", ["note_version", "facility_change"])
async def test_database_refuses_truncating_the_record(engine: AsyncEngine, table: str) -> None:
    with pytest.raises(DBAPIError, match=rf"{table}.*not allowed"):
        async with engine.begin() as conn:
            await conn.execute(text(f"TRUNCATE {table}"))


@pytest.mark.asyncio
async def test_facility_change_without_author_is_only_for_version_one(
    engine: AsyncEngine,
) -> None:
    ids = await _build_world(engine)
    with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
            await conn.execute(
                insert(tables.facility_change).values(
                    id=_id(),
                    facility_id=ids["facility"],
                    version=2,
                    changed_by=None,
                    changed_at=NOW,
                    settings={},
                )
            )


@pytest.mark.asyncio
async def test_admin_alone_has_no_facility(engine: AsyncEngine) -> None:
    ids = await _build_world(engine)
    base = {"display_name": "Demo", "initials": "D"}
    async with engine.begin() as conn:
        await conn.execute(
            insert(tables.app_user).values(id=_id(), role=Role.ADMIN, facility_id=None, **base)
        )
    with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
            await conn.execute(
                insert(tables.app_user).values(
                    id=_id(), role=Role.ADMIN, facility_id=ids["facility"], **base
                )
            )
    with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
            await conn.execute(
                insert(tables.app_user).values(
                    id=_id(), role=Role.HEAD_NURSE, facility_id=None, **base
                )
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["", "A" * 64, "g" * 64, "a" * 63, "a" * 65])
async def test_content_hash_must_be_lowercase_hex(engine: AsyncEngine, bad: str) -> None:
    ids = await _build_world(engine)
    note = _note_values(ids)
    async with engine.begin() as conn:
        await conn.execute(insert(tables.note).values(note))
    with pytest.raises(IntegrityError, match="ck_note_content_hash_is_hex"):
        async with engine.begin() as conn:
            await conn.execute(
                update(tables.note)
                .where(tables.note.c.id == note["id"])
                .values(
                    status=NoteStatus.SIGNED,
                    version=2,
                    signed_by=ids["nurse"],
                    signed_at=NOW,
                    content_hash=bad,
                )
            )
    # The version's own check, past the guard that wants the signed note's hash (which is hex).
    # The guard is switched off inside a transaction that is rolled back, so it comes back on.
    async with engine.connect() as conn:
        await conn.execute(
            text("ALTER TABLE note_version DISABLE TRIGGER note_version_only_of_a_signed_note")
        )
        with pytest.raises(IntegrityError, match="ck_note_version_content_hash_is_hex"):
            await conn.execute(
                insert(tables.note_version).values(
                    _version_values(note["id"], ids) | {"content_hash": bad}
                )
            )
        await conn.rollback()


@pytest.mark.asyncio
async def test_a_job_has_a_failure_only_when_failed(engine: AsyncEngine) -> None:
    ids = await _build_world(engine)
    with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
            await conn.execute(
                insert(tables.draft_job).values(
                    id=_id(),
                    rough_note_id=ids["rough_note"],
                    status=JobStatus.QUEUED,
                    failure=JobFailure.PROVIDER_ERROR,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )


@pytest.mark.asyncio
async def test_an_idempotency_key_is_scoped_to_its_author(engine: AsyncEngine) -> None:
    ids = await _build_world(engine)
    duplicate = {
        "id": _id(),
        "encounter_id": ids["encounter"],
        "author_id": ids["nurse"],
        "text": "again",
        "written_at": NOW,
        "note_format": NoteFormat.FDAR,
        "shift_code": "6-2",
        "shift_label": "6-2",
        "shift_starts_at": NOW,
        "shift_ends_at": NOW + timedelta(hours=8),
        "shift_date": date(2026, 11, 15),
        "shift_timezone": "Asia/Manila",
        "idempotency_key": "key-1",
        "body_hash": HASH,
    }
    with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
            await conn.execute(insert(tables.rough_note).values(duplicate))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("table", "column", "enum"),
    [
        ("facility", "locale", Locale),
        ("facility", "default_note_format", NoteFormat),
        ("shift_definition", "ink", ShiftInk),
        ("app_user", "role", Role),
        ("rough_note", "note_format", NoteFormat),
        ("draft_job", "status", JobStatus),
        ("draft_job", "failure", JobFailure),
        ("note", "status", NoteStatus),
    ],
)
async def test_enum_checks_list_exactly_the_enum_values(
    engine: AsyncEngine, table: str, column: str, enum: type[StrEnum]
) -> None:
    async with engine.connect() as conn:
        definition = (
            await conn.execute(
                text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"),
                {"n": f"ck_{table}_{column}_values"},
            )
        ).scalar_one()
    for member in enum:
        assert f"'{member.value}'" in definition
    assert definition.count("::text") == len(enum)


async def _constraint_definition(engine: AsyncEngine, name: str) -> str:
    async with engine.connect() as conn:
        return (
            await conn.execute(
                text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"),
                {"n": name},
            )
        ).scalar_one()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("column", "allowed"),
    [
        ("unit_temperature", TEMPERATURE_UNITS),
        ("unit_weight", WEIGHT_UNITS),
        ("unit_volume", VOLUME_UNITS),
        ("clock", set(get_args(FacilitySettings.model_fields["clock"].annotation))),
    ],
)
async def test_unit_and_clock_checks_list_exactly_the_domain_values(
    engine: AsyncEngine, column: str, allowed: set[str]
) -> None:
    definition = await _constraint_definition(engine, f"ck_facility_{column}_values")
    for value in allowed:
        assert f"'{value}'" in definition
    assert definition.count("::text") == len(allowed)


@pytest.mark.asyncio
async def test_facility_note_formats_hold_only_known_formats(engine: AsyncEngine) -> None:
    definition = await _constraint_definition(engine, "ck_facility_note_formats_values")
    for member in NoteFormat:
        assert f"'{member.value}'" in definition
    assert definition.count("::text") == len(NoteFormat)
    await _build_world(engine)
    with pytest.raises(IntegrityError, match="ck_facility_note_formats_values"):
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE facility SET note_formats = ARRAY['fdar', 'soap'], "
                    "default_note_format = 'fdar'"
                )
            )


SIGNED_ALL: dict[str, Any] = {"signed_by": "nurse", "signed_at": NOW, "content_hash": HASH}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "extra", "constraint"),
    [
        ("draft", {"signed_by": "nurse"}, "signature_only_when_signed"),
        ("draft", {"signed_at": NOW}, "signature_only_when_signed"),
        ("draft", {"content_hash": HASH}, "signature_only_when_signed"),
        ("signed", {"signed_by": "nurse", "signed_at": NOW}, "signature_only_when_signed"),
        ("draft", {"discarded_by": "nurse"}, "discard_only_when_discarded"),
        ("draft", {"discarded_at": NOW}, "discard_only_when_discarded"),
        ("discarded", {"discarded_by": "nurse"}, "discard_only_when_discarded"),
        ("signed", SIGNED_ALL | {"discarded_at": NOW}, "discard_only_when_discarded"),
    ],
)
async def test_a_note_never_holds_part_of_a_signature_or_discard(
    engine: AsyncEngine, status: str, extra: dict[str, Any], constraint: str
) -> None:
    ids = await _build_world(engine)
    values = _note_values(ids) | {"status": status}
    values |= {k: ids["nurse"] if v == "nurse" else v for k, v in extra.items()}
    with pytest.raises(IntegrityError, match=f"ck_note_{constraint}"):
        async with engine.begin() as conn:
            await conn.execute(insert(tables.note).values(values))


@pytest.mark.asyncio
async def test_the_secondary_indexes_exist(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        found = set((await conn.execute(text("SELECT indexname FROM pg_indexes"))).scalars().all())
    assert {
        "ix_rough_note_encounter_id_shift_starts_at",
        "ix_draft_job_status",
        "ix_ai_usage_created_at",
        "ix_session_user_id",
    } <= found
