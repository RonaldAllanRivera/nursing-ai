"""POST /events: the worker's SQS records. A bad record is dropped; a failed job is still 200."""

import json
from datetime import timedelta
from typing import Any, Literal
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from nursing_api.app import create_app
from nursing_api.settings import Settings
from nursing_core.demo import load_demo_cases
from nursing_core.domain.errors import DatabaseWaking
from nursing_core.domain.jobs import JobFailure, JobStatus
from nursing_core.storage import tables
from sqlalchemy import func, select

from .helpers import PH_STAFF, MutableClock, client_for, running_app

UNUSED = "postgresql+asyncpg://unused@localhost/unused"
PH_CASE = next(case for case in load_demo_cases() if case.facility_key == "ph-demo")


def records(*bodies: str) -> dict[str, Any]:
    return {"Records": [{"messageId": str(uuid4()), "body": body} for body in bodies]}


def message(job_id: UUID) -> str:
    return json.dumps({"job_id": str(job_id)})


async def add_job(app: FastAPI, key: str = "key-1") -> UUID:
    record = await app.state.patients.get_patient(PH_CASE.patient_id)
    rough = PH_CASE.rough_note.model_copy(
        update={"id": uuid4(), "author_id": PH_STAFF, "encounter_id": record.encounter_id}
    )
    _, job = await app.state.notes.add_rough_note(rough, key, "a" * 64)
    return job.id


async def count(app: FastAPI, table: Any) -> int:
    async with app.state.engine.connect() as conn:
        return await conn.scalar(select(func.count()).select_from(table)) or 0


@pytest.mark.asyncio
@pytest.mark.parametrize(("role", "present"), [("api", False), ("worker", True), ("ops", True)])
async def test_events_route_exists_only_for_worker_and_ops(
    role: Literal["api", "worker", "ops"], present: bool
) -> None:
    app = create_app(Settings(database_url=UNUSED, app_role=role))
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        status = (await client.post("/events", json={})).status_code
    assert (status != 404) is present


@pytest.mark.asyncio
async def test_redelivered_message_after_success_is_a_no_op(
    database_url: str, clock: MutableClock
) -> None:
    async with running_app(database_url, clock, app_role="worker") as app:
        job_id = await add_job(app)
        async with client_for(app) as client:
            first = await client.post("/events", json=records(message(job_id)))
            second = await client.post("/events", json=records(message(job_id)))
        job = await app.state.notes.get_job(job_id)
        assert (first.status_code, second.status_code) == (200, 200)
        assert job.status is JobStatus.SUCCEEDED
        assert await count(app, tables.note) == 1
        assert (await app.state.usage.month_total(clock.now()))[1] == 1


@pytest.mark.asyncio
async def test_malformed_record_is_dropped_not_retried(
    database_url: str, clock: MutableClock
) -> None:
    async with running_app(database_url, clock, app_role="worker") as app:
        job_id = await add_job(app)
        batch = records("not json", json.dumps({"job_id": "nope"}), "[]", message(job_id))
        async with client_for(app) as client:
            response = await client.post("/events", json=batch)
        assert response.status_code == 200
        assert (await app.state.notes.get_job(job_id)).status is JobStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_a_failed_job_still_answers_200(database_url: str, clock: MutableClock) -> None:
    async with running_app(database_url, clock, app_role="worker") as app:
        job_id = await add_job(app)
        async with app.state.engine.begin() as conn:
            await conn.execute(
                tables.draft_job.update()
                .where(tables.draft_job.c.id == job_id)
                .values(attempts=3, status="running", claimed_at=clock.now() - timedelta(hours=1))
            )
        async with client_for(app) as client:
            response = await client.post("/events", json=records(message(job_id)))
        job = await app.state.notes.get_job(job_id)
    assert response.status_code == 200
    assert (job.status, job.failure) == (JobStatus.FAILED, JobFailure.PROVIDER_ERROR)


@pytest.mark.asyncio
async def test_a_database_that_stays_asleep_answers_503_so_sqs_redelivers(
    database_url: str, clock: MutableClock
) -> None:
    async with running_app(database_url, clock, app_role="worker") as app:
        app.state.worker.run = AsyncMock(side_effect=DatabaseWaking("waking"))
        async with client_for(app) as client:
            response = await client.post("/events", json=records(message(uuid4())))
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_a_job_whose_outcome_cannot_be_recorded_answers_5xx(
    database_url: str, clock: MutableClock
) -> None:
    async with running_app(database_url, clock, app_role="worker") as app:
        job_id = await add_job(app)
        app.state.notes.complete_job = AsyncMock(side_effect=OSError("db down"))
        app.state.notes.fail_job = AsyncMock(side_effect=OSError("db down"))
        async with client_for(app) as client:
            response = await client.post("/events", json=records(message(job_id)))
    assert response.status_code >= 500
