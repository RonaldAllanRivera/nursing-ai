"""The draft worker: real pipeline, provider choice per AI_MODE, the budget guard, failures."""

import asyncio
import logging
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from nursing_api.app import create_app
from nursing_api.settings import Settings
from nursing_core.db import create_engine
from nursing_core.demo import DemoCase, load_demo_cases
from nursing_core.domain.errors import (
    AiBudgetReached,
    InvalidModelOutput,
    ModelRefused,
    PhiLeak,
    ProviderUnavailable,
)
from nursing_core.domain.jobs import JobFailure, JobStatus
from nursing_core.domain.model_output import DraftRequest, ProviderResult
from nursing_core.domain.notes import GenerationInfo, RoughNote
from nursing_core.domain.patient import PatientRecord
from nursing_core.pipeline.fdar import run_fdar_pipeline
from nursing_core.ports import LlmProvider
from nursing_core.providers.fake import FakeProvider
from nursing_core.storage.repositories import PgNoteRepository, PgPatientRepository
from pydantic import SecretStr

from .helpers import (
    PH_STAFF,
    STAFF_NURSE,
    MutableClock,
    client_for,
    post_note,
    running_app,
    sign_in,
)

CASES = load_demo_cases()
PH_CASE = next(case for case in CASES if case.facility_key == "ph-demo")
TEST_KEY = SecretStr("sk-ant-test-not-real")


class SpyProvider:
    """Records every request it gets and answers with a case's canned draft."""

    def __init__(self, case: DemoCase = PH_CASE) -> None:
        self.requests: list[DraftRequest] = []
        self._inner = FakeProvider(case.model_output)

    async def draft_fdar(self, request: DraftRequest) -> ProviderResult:
        self.requests.append(request)
        return await self._inner.draft_fdar(request)


class FailingProvider:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def draft_fdar(self, request: DraftRequest) -> ProviderResult:
        del request
        raise self.error


async def post_and_finish(
    app: FastAPI, client: httpx.AsyncClient, case: DemoCase = PH_CASE, text: str | None = None
) -> dict[str, object]:
    posted = await post_note(client, case.patient_id, text or case.rough_note.text)
    assert posted.status_code == 202, posted.text
    await app.state.queue.drain()
    job = await client.get(f"/api/v1/draft-jobs/{posted.json()['id']}")
    assert job.status_code == 200
    body: dict[str, object] = job.json()
    return body


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=[case.key for case in CASES])
async def test_job_runs_to_a_draft_with_fake_provider(
    database_url: str, clock: MutableClock, case: DemoCase
) -> None:
    clock.set(case.rough_note.written_at)
    async with running_app(database_url, clock) as app, client_for(app) as client:
        await sign_in(client, STAFF_NURSE[case.facility_key])
        job = await post_and_finish(app, client, case)
    assert job["status"] == "succeeded", job
    note = await app.state.notes.get_note(UUID(str(job["note_id"])))
    assert note.draft == case.expected_draft
    assert note.checklist == case.expected_checklist
    assert note.status == "draft"
    assert note.version == 1
    assert note.signature is None
    assert note.generation.provider == "fake"
    total, calls = await app.state.usage.month_total(clock.now())
    assert (total, calls) == (Decimal(0), 1)


@pytest.mark.asyncio
async def test_a_patient_without_a_demo_case_fails_with_replay_missing(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    await sign_in(client, PH_STAFF)
    with_case = {case.patient_id for case in CASES}
    summaries = await app.state.patients.list_patients("ph-demo")
    bare = next(p for p in summaries if p.id not in with_case)
    posted = await post_note(client, bare.id, "pt resting")
    await app.state.queue.drain()
    job = (await client.get(f"/api/v1/draft-jobs/{posted.json()['id']}")).json()
    assert (job["status"], job["failure"], job["note_id"]) == ("failed", "replay_missing", None)
    assert (await app.state.usage.month_total(app.state.clock.now()))[1] == 0


@pytest.mark.asyncio
async def test_replay_mode_without_a_recording_fails_with_replay_missing(
    database_url: str, clock: MutableClock
) -> None:
    async with (
        running_app(database_url, clock, ai_mode="replay") as app,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        await sign_in(client, PH_STAFF)
        job = await post_and_finish(app, client)
    assert (job["status"], job["failure"]) == ("failed", "replay_missing")


@pytest.mark.asyncio
async def test_the_provider_gets_the_redacted_text_only(
    database_url: str, clock: MutableClock
) -> None:
    spy = SpyProvider()
    async with (
        running_app(database_url, clock, provider_for=lambda _patient: spy) as app,
        client_for(app) as client,
    ):
        await sign_in(client, PH_STAFF)
        await post_and_finish(app, client)
    assert len(spy.requests) == 1
    request = spy.requests[0]
    given = PH_CASE.patient.given_name.lower()
    assert given not in request.redacted_text.lower()


@pytest.mark.asyncio
async def test_the_provider_factory_receives_the_notes_patient(
    database_url: str, clock: MutableClock
) -> None:
    seen: list[PatientRecord] = []

    def factory(patient: PatientRecord) -> LlmProvider:
        seen.append(patient)
        return SpyProvider()

    async with (
        running_app(database_url, clock, provider_for=factory) as app,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        await sign_in(client, PH_STAFF)
        await post_and_finish(app, client)
    assert [record.summary.id for record in seen] == [PH_CASE.patient_id]


@pytest.mark.asyncio
async def test_the_worker_passes_the_shifts_rough_notes_to_the_pipeline(
    database_url: str, clock: MutableClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    earlier_seen: list[list[RoughNote]] = []
    real = run_fdar_pipeline

    async def spying_pipeline(
        note: RoughNote,
        patient: PatientRecord,
        earlier: list[RoughNote],
        provider: LlmProvider,
    ) -> object:
        earlier_seen.append(list(earlier))
        return await real(note, patient, earlier, provider)

    monkeypatch.setattr("nursing_api.worker.run_fdar_pipeline", spying_pipeline)
    async with (
        running_app(database_url, clock) as app,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        await sign_in(client, PH_STAFF)
        first = await post_note(client, PH_CASE.patient_id, "first note", key="a")
        await app.state.queue.drain()
        clock.advance(timedelta(minutes=1))
        second = await post_note(client, PH_CASE.patient_id, "second note", key="b")
        await app.state.queue.drain()
    # The pipeline itself ignores the note being drafted and anything written after it.
    first_id = UUID(first.json()["rough_note_id"])
    second_id = UUID(second.json()["rough_note_id"])
    assert [rough.id for rough in earlier_seen[0]] == [first_id]
    assert [rough.id for rough in earlier_seen[1]] == [first_id, second_id]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "failure"),
    [
        (AiBudgetReached("x"), JobFailure.AI_BUDGET_REACHED),
        (ModelRefused("x"), JobFailure.MODEL_REFUSED),
        (InvalidModelOutput("x"), JobFailure.INVALID_OUTPUT),
        (ProviderUnavailable("x"), JobFailure.PROVIDER_ERROR),
        (PhiLeak("x"), JobFailure.PROVIDER_ERROR),
        (RuntimeError("x"), JobFailure.PROVIDER_ERROR),
    ],
)
async def test_provider_errors_map_to_job_failures(
    database_url: str, clock: MutableClock, error: Exception, failure: JobFailure
) -> None:
    provider = FailingProvider(error)
    async with (
        running_app(database_url, clock, provider_for=lambda _patient: provider) as app,
        client_for(app) as client,
    ):
        await sign_in(client, PH_STAFF)
        job = await post_and_finish(app, client)
    assert job["status"] == "failed"
    assert job["failure"] == failure.value
    assert (await app.state.usage.month_total(clock.now()))[1] == 0


@pytest.mark.asyncio
async def test_budget_error_from_provider_fails_job_as_budget_reached(
    database_url: str, clock: MutableClock
) -> None:
    provider = FailingProvider(AiBudgetReached("the console limit"))
    async with (
        running_app(database_url, clock, provider_for=lambda _patient: provider) as app,
        client_for(app) as client,
    ):
        await sign_in(client, PH_STAFF)
        job = await post_and_finish(app, client)
    assert (job["status"], job["failure"]) == ("failed", "ai_budget_reached")


@pytest.mark.asyncio
async def test_a_failure_logs_the_job_and_the_error_class_only(
    database_url: str, clock: MutableClock, caplog: pytest.LogCaptureFixture
) -> None:
    canary = "zebracanary-error-text"
    provider = FailingProvider(RuntimeError(canary))
    caplog.set_level(logging.DEBUG)
    async with (
        running_app(database_url, clock, provider_for=lambda _patient: provider) as app,
        client_for(app) as client,
    ):
        await sign_in(client, PH_STAFF)
        await post_and_finish(app, client)
    assert canary not in caplog.text


def live_settings(database_url: str, **values: object) -> Settings:
    return Settings.model_validate(
        {
            "database_url": database_url,
            "ai_mode": "live",
            "ai_monthly_cap_usd": "1.00",
            "anthropic_api_key": TEST_KEY,
            **values,
        }
    )


@pytest.mark.parametrize("missing", ["ai_monthly_cap_usd", "anthropic_api_key"])
def test_live_mode_refuses_without_cap(missing: str) -> None:
    values = {"ai_monthly_cap_usd": "1.00", "anthropic_api_key": TEST_KEY}
    values.pop(missing)
    settings = Settings.model_validate(
        {"database_url": "postgresql+asyncpg://unused@localhost/unused", "ai_mode": "live"} | values
    )
    with pytest.raises(ValueError, match="live"):
        create_app(settings)


def test_live_mode_with_cap_and_key_builds() -> None:
    settings = live_settings("postgresql+asyncpg://unused@localhost/unused")
    assert create_app(settings) is not None


async def record_spend(app: FastAPI, cost: str) -> None:
    generation = GenerationInfo(
        provider="anthropic",
        model="claude-opus-5-5",
        prompt_version="fdar-v1",
        input_tokens=1,
        output_tokens=1,
        cost_usd=Decimal(cost),
        latency_ms=1,
    )
    await app.state.usage.record(None, generation, app.state.clock.now())


@pytest.mark.asyncio
async def test_cap_reached_fails_job_without_calling_provider(
    database_url: str, clock: MutableClock
) -> None:
    spy = SpyProvider()
    settings = live_settings(database_url)  # cap $1.00
    app = create_app(settings, clock=clock, provider_for=lambda _patient: spy)
    async with app.router.lifespan_context(app):
        await record_spend(app, "0.90")  # the worst-case estimate of one call is more than 10c
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            await sign_in(client, PH_STAFF)
            job = await post_and_finish(app, client)
        assert (job["status"], job["failure"]) == ("failed", "ai_budget_reached")
        assert spy.requests == []
        assert (await app.state.usage.month_total(clock.now()))[1] == 1  # only the planted row


@pytest.mark.asyncio
async def test_a_call_within_the_cap_goes_through_and_is_recorded(
    database_url: str, clock: MutableClock
) -> None:
    spy = SpyProvider()
    settings = live_settings(database_url, ai_monthly_cap_usd="100.00")
    app = create_app(settings, clock=clock, provider_for=lambda _patient: spy)
    async with app.router.lifespan_context(app):
        await record_spend(app, "0.90")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            await sign_in(client, PH_STAFF)
            job = await post_and_finish(app, client)
        assert job["status"] == "succeeded"
        assert len(spy.requests) == 1
        assert (await app.state.usage.month_total(clock.now()))[1] == 2


@pytest.mark.asyncio
async def test_the_cap_counts_this_utc_month_only(database_url: str, clock: MutableClock) -> None:
    spy = SpyProvider()
    app = create_app(live_settings(database_url), clock=clock, provider_for=lambda _p: spy)
    async with app.router.lifespan_context(app):
        await record_spend(app, "0.90")
        clock.set(clock.now().replace(month=12, day=2))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            await sign_in(client, PH_STAFF)
            job = await post_and_finish(app, client)
    assert job["status"] == "succeeded"


@pytest.mark.asyncio
async def test_startup_requeues_queued_jobs_and_fails_running_ones(
    database_url: str, clock: MutableClock
) -> None:
    engine = create_engine(database_url)
    try:
        notes = PgNoteRepository(engine, clock)
        patients = PgPatientRepository(engine, clock)
        record = await patients.get_patient(PH_CASE.patient_id)
        template = PH_CASE.rough_note

        async def add(key: str) -> UUID:
            rough = template.model_copy(
                update={"id": uuid4(), "author_id": PH_STAFF, "encounter_id": record.encounter_id}
            )
            _, job = await notes.add_rough_note(rough, key, sha256(key.encode()).hexdigest())
            return job.id

        queued, running = await add("queued"), await add("running")
        assert await notes.claim_job(running) is not None
    finally:
        await engine.dispose()
    async with running_app(database_url, clock) as app:
        await app.state.queue.drain()
        done = await app.state.notes.get_job(queued)
        crashed = await app.state.notes.get_job(running)
    assert done.status is JobStatus.SUCCEEDED
    assert (crashed.status, crashed.failure) == (JobStatus.FAILED, JobFailure.PROVIDER_ERROR)


@pytest.mark.asyncio
async def test_shutdown_cancels_a_job_that_will_not_finish(
    database_url: str, clock: MutableClock
) -> None:
    started = asyncio.Event()

    class Stuck:
        async def draft_fdar(self, request: DraftRequest) -> ProviderResult:
            del request
            started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    stuck = Stuck()
    async with (
        running_app(database_url, clock, provider_for=lambda _patient: stuck) as app,
        client_for(app) as client,
    ):
        await sign_in(client, PH_STAFF)
        await post_note(client, PH_CASE.patient_id, "pt resting")
    await asyncio.wait_for(started.wait(), 5)
    await app.state.queue.close(wait_seconds=0.05)
    assert app.state.queue.pending == 0
