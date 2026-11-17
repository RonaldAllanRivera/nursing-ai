"""Try drafting again: a new job after a retryable failure, and the open job for a double tap."""

import asyncio
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from nursing_core.demo import load_demo_cases
from nursing_core.domain.errors import AiBudgetReached, ProviderUnavailable
from nursing_core.domain.model_output import DraftRequest, ProviderResult
from nursing_core.domain.patient import PatientRecord
from nursing_core.ports import LlmProvider
from nursing_core.providers.fake import FakeProvider

from .helpers import (
    PH_STAFF,
    US_STAFF,
    MutableClock,
    client_for,
    post_note,
    running_app,
    sign_in,
)
from .test_budget import add_invited_nurse

PH_CASE = next(case for case in load_demo_cases() if case.facility_key == "ph-demo")


class SwitchableProvider:
    """Fails with `error` until a test clears it, then drafts the demo case; can wait on a gate."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.gate: asyncio.Event | None = None
        self.calls = 0
        self._inner = FakeProvider(PH_CASE.model_output)

    async def draft_fdar(self, request: DraftRequest) -> ProviderResult:
        self.calls += 1
        if self.gate is not None:
            await self.gate.wait()
        if self.error is not None:
            raise self.error
        return await self._inner.draft_fdar(request)

    def for_patient(self, _patient: PatientRecord) -> LlmProvider:
        return self


def draft_path(rough_note_id: object) -> str:
    return f"/api/v1/rough-notes/{rough_note_id}/draft-jobs"


async def failed_note(
    app: FastAPI, client: httpx.AsyncClient, error: Exception, key: str = "key-1"
) -> dict[str, object]:
    """Posts a rough note whose first job fails with `error`; returns that job."""
    posted = await post_note(client, PH_CASE.patient_id, "pt resting", key=key)
    assert posted.status_code == 202, posted.text
    await app.state.queue.drain()
    job = (await client.get(f"/api/v1/draft-jobs/{posted.json()['id']}")).json()
    assert job["status"] == "failed"
    return job


@pytest.mark.asyncio
async def test_try_again_after_a_provider_error_makes_a_new_job(
    database_url: str, clock: MutableClock
) -> None:
    provider = SwitchableProvider(ProviderUnavailable("x"))
    async with (
        running_app(database_url, clock, provider_for=provider.for_patient) as app,
        client_for(app) as client,
    ):
        await sign_in(client, PH_STAFF)
        failed = await failed_note(app, client, provider.error or RuntimeError())
        assert (failed["failure"], failed["retryable"]) == ("provider_error", True)
        provider.error = None
        clock.advance(timedelta(minutes=1))

        again = await client.post(draft_path(failed["rough_note_id"]))

        assert again.status_code == 202, again.text
        job = again.json()
        assert job["id"] != failed["id"]
        assert job["rough_note_id"] == failed["rough_note_id"]
        assert again.headers["location"] == f"/api/v1/draft-jobs/{job['id']}"
        await app.state.queue.drain()
        done = (await client.get(f"/api/v1/draft-jobs/{job['id']}")).json()
        assert (done["status"], done["note_id"] is not None) == ("succeeded", True)
        # The failed job stays as history.
        old = (await client.get(f"/api/v1/draft-jobs/{failed['id']}")).json()
        assert (old["status"], old["failure"]) == ("failed", "provider_error")


@pytest.mark.asyncio
async def test_try_again_while_drafting_returns_the_open_job(
    database_url: str, clock: MutableClock
) -> None:
    provider = SwitchableProvider()
    provider.gate = asyncio.Event()
    async with (
        running_app(database_url, clock, provider_for=provider.for_patient) as app,
        client_for(app) as client,
    ):
        await sign_in(client, PH_STAFF)
        posted = (await post_note(client, PH_CASE.patient_id, "pt resting")).json()

        first = await client.post(draft_path(posted["rough_note_id"]))
        second = await client.post(draft_path(posted["rough_note_id"]))

        for response in (first, second):
            assert response.status_code == 202, response.text
            assert response.json()["id"] == posted["id"]
            assert response.headers["location"] == f"/api/v1/draft-jobs/{posted['id']}"
        provider.gate.set()
        await app.state.queue.drain()
        assert provider.calls == 1  # the taps made no second job


@pytest.mark.asyncio
async def test_try_again_after_success_is_409_already_drafted(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    await sign_in(client, PH_STAFF)
    posted = (await post_note(client, PH_CASE.patient_id, PH_CASE.rough_note.text)).json()
    await app.state.queue.drain()
    assert (await client.get(f"/api/v1/draft-jobs/{posted['id']}")).json()["status"] == "succeeded"

    again = await client.post(draft_path(posted["rough_note_id"]))

    assert again.status_code == 409
    assert again.json()["code"] == "already_drafted"


@pytest.mark.asyncio
async def test_try_again_after_the_budget_is_reached_is_409_not_retryable(
    database_url: str, clock: MutableClock
) -> None:
    provider = SwitchableProvider(AiBudgetReached("x"))
    async with (
        running_app(database_url, clock, provider_for=provider.for_patient) as app,
        client_for(app) as client,
    ):
        await sign_in(client, PH_STAFF)
        failed = await failed_note(app, client, AiBudgetReached("x"))
        assert (failed["failure"], failed["retryable"]) == ("ai_budget_reached", False)

        again = await client.post(draft_path(failed["rough_note_id"]))

        assert again.status_code == 409
        assert again.json()["code"] == "not_retryable"
        assert provider.calls == 1


@pytest.mark.asyncio
async def test_only_the_author_can_try_again(database_url: str, clock: MutableClock) -> None:
    provider = SwitchableProvider(ProviderUnavailable("x"))
    async with (
        running_app(database_url, clock, provider_for=provider.for_patient) as app,
        client_for(app) as author,
        client_for(app) as colleague,
        client_for(app) as other_facility,
    ):
        await sign_in(author, PH_STAFF)
        failed = await failed_note(app, author, ProviderUnavailable("x"))
        path = draft_path(failed["rough_note_id"])
        await sign_in(colleague, await add_invited_nurse(app, "ph-demo"))
        await sign_in(other_facility, US_STAFF)

        assert (await colleague.post(path)).status_code == 403
        assert (await other_facility.post(path)).status_code == 404
        assert (await author.post(f"/api/v1/rough-notes/{uuid4()}/draft-jobs")).status_code == 404
        assert provider.calls == 1  # nobody else's tap made a job


@pytest.mark.asyncio
async def test_try_again_is_counted_by_the_daily_cap_only_when_it_makes_a_job(
    database_url: str, clock: MutableClock
) -> None:
    provider = SwitchableProvider(ProviderUnavailable("x"))
    async with (
        running_app(
            database_url, clock, provider_for=provider.for_patient, ai_daily_drafts_per_user=2
        ) as app,
        client_for(app) as client,
    ):
        await sign_in(client, await add_invited_nurse(app, "ph-demo"))
        failed = await failed_note(app, client, ProviderUnavailable("x"))
        clock.advance(timedelta(minutes=1))
        second = await client.post(draft_path(failed["rough_note_id"]))
        assert second.status_code == 202
        await app.state.queue.drain()  # fails again with the same error
        clock.advance(timedelta(minutes=1))

        third = await client.post(draft_path(failed["rough_note_id"]))

        assert third.status_code == 429
        assert third.json()["code"] == "daily_draft_limit"


@pytest.mark.asyncio
async def test_shift_list_shows_the_newest_job(database_url: str, clock: MutableClock) -> None:
    provider = SwitchableProvider(ProviderUnavailable("x"))
    async with (
        running_app(database_url, clock, provider_for=provider.for_patient) as app,
        client_for(app) as client,
    ):
        await sign_in(client, PH_STAFF)
        failed = await failed_note(app, client, ProviderUnavailable("x"))
        provider.error = None
        clock.advance(timedelta(minutes=1))
        retry = (await client.post(draft_path(failed["rough_note_id"]))).json()
        await app.state.queue.drain()

        detail = (await client.get(f"/api/v1/patients/{PH_CASE.patient_id}")).json()

        assert [n["job"]["id"] for n in detail["notes"]] == [retry["id"]]
        assert detail["notes"][0]["job"]["status"] == "succeeded"
        assert detail["notes"][0]["note_status"] == "draft"
