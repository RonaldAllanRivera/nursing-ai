"""The mock-HIS importer: validate the whole file first, then upsert every chart together."""

import asyncio
import json
import os
import subprocess
import sys
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from nursing_core.clock import FixedClock
from nursing_core.domain.patient import PatientRecord
from nursing_core.storage.his_import import HisFileError, import_his, parse_his
from nursing_core.storage.repositories import PgPatientRepository
from nursing_core.storage.seed import seed
from sqlalchemy.ext.asyncio import AsyncEngine

CLOCK = FixedClock(datetime(2026, 11, 12, 9, 0, tzinfo=UTC))
FIXTURE = Path(__file__).parent / "fixtures" / "mock_his.json"


def fixture_data() -> dict[str, object]:
    data: object = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data  # pyright: ignore[reportUnknownVariableType]


@pytest_asyncio.fixture
async def seeded(engine: AsyncEngine) -> AsyncEngine:
    await seed(engine, CLOCK)
    return engine


async def read(engine: AsyncEngine, record_number: str) -> PatientRecord:
    repo = PgPatientRepository(engine, CLOCK)
    for summary in await repo.list_patients("ph-demo"):
        found = await repo.get_patient(summary.id)
        if found.identity.record_number == record_number:
            return found
    raise AssertionError(record_number)


def with_entry_change(path: list[str | int], value: object) -> dict[str, object]:
    """The fixture with one value replaced, to make it invalid in one place."""
    data = deepcopy(fixture_data())
    target: Any = data
    for step in path[:-1]:
        target = target[step]
    target[path[-1]] = value
    return data


def test_the_fixture_is_a_valid_file() -> None:
    his = parse_his(fixture_data())
    assert his.facility_key == "ph-demo"
    assert [p.record_number for p in his.patients] == ["SYN-PH-0004", "SYN-PH-0005"]


def test_importer_rejects_bad_context() -> None:
    bad_unit = "ZZ-BAD-VALUE"
    data = with_entry_change(
        ["patients", 1, "context", "latest_vitals"],
        {"taken_at": "2026-11-12T06:00:00+08:00", "pulse": {"value": "78", "unit": bad_unit}},
    )
    with pytest.raises(HisFileError) as raised:
        parse_his(data)
    message = str(raised.value)
    assert "patients[1].context.latest_vitals.pulse.unit" in message
    assert bad_unit not in message
    assert "78" not in message


@pytest.mark.parametrize(
    ("path", "value", "where"),
    [
        (["synthetic"], False, "synthetic"),
        (["facility_key"], 12345, "facility_key"),
        (["patients", 0, "record_number"], 12345, "patients[0].record_number"),
        (["patients", 0, "context", "code_status"], 12345, "patients[0].context.code_status"),
        (["patients", 1, "context", "extra"], "x", "patients[1].context.extra"),
    ],
)
def test_parse_names_the_field_of_the_problem(
    path: list[str | int], value: object, where: str
) -> None:
    with pytest.raises(HisFileError) as raised:
        parse_his(with_entry_change(path, value))
    assert where in str(raised.value)
    assert "12345" not in str(raised.value)


def test_a_real_looking_file_that_is_not_marked_synthetic_is_refused() -> None:
    data = fixture_data()
    del data["synthetic"]
    with pytest.raises(HisFileError, match="synthetic"):
        parse_his(data)


@pytest.mark.parametrize("data", [[], "text", 3, None, {}])
def test_a_file_that_is_not_the_right_shape_is_refused(data: object) -> None:
    with pytest.raises(HisFileError):
        parse_his(data)


@pytest.mark.asyncio
async def test_import_replaces_the_context_on_the_open_encounter(seeded: AsyncEngine) -> None:
    before = await read(seeded, "SYN-PH-0004")
    other = await read(seeded, "SYN-PH-0006")
    count = await import_his(seeded, parse_his(fixture_data()), CLOCK)
    assert count == 2
    after = await read(seeded, "SYN-PH-0004")
    assert after.encounter_id == before.encounter_id
    assert after.identity == before.identity
    assert after.context.allergies == ["shellfish (hives)"]
    assert after.context.latest_vitals is not None
    assert after.context.latest_vitals.weight is not None
    assert after.context != before.context
    assert (await read(seeded, "SYN-PH-0006")).context == other.context


@pytest.mark.asyncio
async def test_importing_the_same_file_twice_changes_nothing(seeded: AsyncEngine) -> None:
    his = parse_his(fixture_data())
    await import_his(seeded, his, CLOCK)
    once = await read(seeded, "SYN-PH-0005")
    assert await import_his(seeded, his, CLOCK) == 2
    assert await read(seeded, "SYN-PH-0005") == once


@pytest.mark.asyncio
async def test_an_unknown_record_number_names_the_entry_and_imports_nothing(
    seeded: AsyncEngine,
) -> None:
    data = with_entry_change(["patients", 1, "record_number"], "SYN-PH-9999")
    before = await read(seeded, "SYN-PH-0004")
    with pytest.raises(HisFileError) as raised:
        await import_his(seeded, parse_his(data), CLOCK)
    assert "patients[1].record_number" in str(raised.value)
    assert "SYN-PH-9999" not in str(raised.value)
    assert (await read(seeded, "SYN-PH-0004")).context == before.context


@pytest.mark.asyncio
async def test_an_unknown_facility_is_refused(seeded: AsyncEngine) -> None:
    data = with_entry_change(["facility_key"], "no-such-place")
    with pytest.raises(HisFileError, match="facility_key"):
        await import_his(seeded, parse_his(data), CLOCK)


@pytest.mark.asyncio
async def test_a_patient_of_another_facility_is_not_found_by_record_number(
    seeded: AsyncEngine,
) -> None:
    data = with_entry_change(["patients", 0, "record_number"], "SYN-US-0001")
    with pytest.raises(HisFileError, match=r"patients\[0\]\.record_number"):
        await import_his(seeded, parse_his(data), CLOCK)


async def run_import(database_url: str, path: Path) -> subprocess.CompletedProcess[bytes]:
    return await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "nursing_core.storage.his_import", str(path)],
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        check=False,
    )


@pytest.mark.asyncio
async def test_import_command_imports_a_file_into_database_url(
    seeded: AsyncEngine, database_url: str
) -> None:
    done = await run_import(database_url, FIXTURE)
    assert done.returncode == 0
    assert (await read(seeded, "SYN-PH-0004")).context.allergies == ["shellfish (hives)"]


@pytest.mark.asyncio
async def test_import_command_names_the_entry_and_not_the_value(
    seeded: AsyncEngine, database_url: str, tmp_path: Path
) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(with_entry_change(["patients", 1, "record_number"], "SYN-PH-9999")))
    done = await run_import(database_url, bad)
    assert done.returncode != 0
    assert b"patients[1].record_number" in done.stderr
    assert b"SYN-PH-9999" not in done.stderr
