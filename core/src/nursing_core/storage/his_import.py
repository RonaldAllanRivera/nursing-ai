"""The mock-HIS importer: read a file of synthetic patient charts and store them.

The file is a JSON object `{"synthetic": true, "facility_key": "...", "patients": [{"record_number":
"...", "context": {...}}]}`, where each context is a `PatientContext` (quantities in UCUM units).
Every entry is checked before anything is written; the contexts are then written together onto
each patient's open encounter, found by record number within the facility.

An error names the entry (`patients[2]`) and the field, and never the value, because a value in a
real file could be a name or a diagnosis. Run it as `python -m nursing_core.storage.his_import
<file>` against `DATABASE_URL`.
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Literal

from pydantic import ValidationError
from pydantic_core import ErrorDetails
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from nursing_core.clock import SystemClock
from nursing_core.db import create_engine
from nursing_core.domain import DomainModel
from nursing_core.domain.patient import PatientContext, Text
from nursing_core.ports import Clock
from nursing_core.storage import tables


class HisFileError(ValueError):
    """A problem with the file. The message names the place, never the value found there."""


class HisPatient(DomainModel):
    record_number: Text
    context: PatientContext


class HisFile(DomainModel):
    synthetic: Literal[True]  # a file that isn't marked synthetic is never imported
    facility_key: Text
    patients: list[HisPatient]


def _place(error: ErrorDetails) -> str:
    """`patients[2].context.latest_vitals`: the path of one error, with no value in it."""
    place = ""
    path = error["loc"]
    if error["type"] == "extra_forbidden":
        path = path[:-1]  # the last step is the file's own unknown key, which could be anything
    for step in path:
        place += f"[{step}]" if isinstance(step, int) else f".{step}" if place else str(step)
    return place or "file"


def parse_his(data: object) -> HisFile:
    """The file's content, checked in full. Raises `HisFileError` naming each field at fault."""
    try:
        return HisFile.model_validate(data)
    except ValidationError as error:
        problems = "; ".join(
            f"{_place(e)} ({'unknown field' if e['type'] == 'extra_forbidden' else e['type']})"
            for e in error.errors()
        )
        raise HisFileError(f"not a valid mock-HIS file: {problems}") from None


async def import_his(engine: AsyncEngine, his: HisFile, clock: Clock) -> int:
    """Store each chart on its patient's open encounter, all or none; returns how many."""
    now = clock.now()
    async with engine.begin() as conn:
        facility_id = (
            await conn.execute(
                select(tables.facility.c.id).where(tables.facility.c.key == his.facility_key)
            )
        ).scalar_one_or_none()
        if facility_id is None:
            raise HisFileError("facility_key: no such facility")
        for index, entry in enumerate(his.patients):
            encounter_id = (
                await conn.execute(
                    select(tables.encounter.c.id)
                    .join(tables.patient, tables.patient.c.id == tables.encounter.c.patient_id)
                    .where(
                        tables.patient.c.facility_id == facility_id,
                        tables.patient.c.record_number == entry.record_number,
                        tables.encounter.c.discharged_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if encounter_id is None:
                raise HisFileError(
                    f"patients[{index}].record_number: no patient with an open encounter"
                )
            context = entry.context.model_dump(mode="json")
            await conn.execute(
                insert(tables.patient_context)
                .values(encounter_id=encounter_id, context=context, updated_at=now)
                .on_conflict_do_update(
                    index_elements=[tables.patient_context.c.encounter_id],
                    set_={"context": context, "updated_at": now},
                )
            )
    return len(his.patients)


def main() -> None:
    """`python -m nursing_core.storage.his_import <file>`: import into `DATABASE_URL`."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set")
    if len(sys.argv) != 2:
        sys.exit("usage: python -m nursing_core.storage.his_import <file>")
    try:
        his = parse_his(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        sys.exit("could not read the file as JSON")
    except HisFileError as error:
        sys.exit(str(error))

    async def run() -> int:
        engine = create_engine(url)
        try:
            return await import_his(engine, his, SystemClock())
        finally:
            await engine.dispose()

    try:
        count = asyncio.run(run())
    except HisFileError as error:
        sys.exit(str(error))
    print(f"imported {count} charts")


if __name__ == "__main__":
    main()
