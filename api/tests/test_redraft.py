"""Try drafting again: a new job after a retryable failure, and the open job for a double tap."""

import asyncio
from datetime import timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from nursing_core.demo import load_demo_cases
from nursing_core.domain.errors import AiBudgetReached, ProviderUnavailable
from sqlalchemy import text

from .helpers import (
    PH_STAFF,
    US_STAFF,
    MutableClock,
    SwitchableProvider,
    add_invited_nurse,
    client_for,
    draft_path,
    post_note,
    running_app,
    sign_in,
)

PH_CASE = next(case for case in load_demo_cases() if case.facility_key == "ph-demo")


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


class FlakyQueue:
    """Stands in for SQS: the first send raises, every later one is recorded and never runs."""

    def __init__(self) -> None:
        self.sent: list[UUID] = []
        self._failed = False

    async def enqueue(self, job_id: UUID) -> None:
        if not self._failed:
            self._failed = True
            raise RuntimeError("the send failed")
        self.sent.append(job_id)

    async def start(self, wait_seconds: float) -> None:
        del wait_seconds

    async def close(self) -> None:
        return None


async def mark_running(app: FastAPI, job_id: str) -> None:
    async with app.state.engine.begin() as conn:
        await conn.execute(
            text("UPDATE draft_job SET status = 'running' WHERE id = :id"),
            {"id": UUID(job_id)},
        )


@pytest.mark.asyncio
async def test_a_replay_sends_the_message_a_failed_send_left_unsent(
    database_url: str, clock: MutableClock
) -> None:
    async with (
        running_app(database_url, clock) as app,
        client_for(app) as client,
    ):
        queue = FlakyQueue()
        app.state.queue = queue
        await sign_in(client, PH_STAFF)
        failed = await post_note(client, PH_CASE.patient_id, "pt resting", key="tap-1")
        assert failed.status_code == 500
        assert queue.sent == []

        replay = await post_note(client, PH_CASE.patient_id, "pt resting", key="tap-1")
        assert replay.status_code == 202, replay.text
        assert queue.sent == [UUID(replay.json()["id"])]

        await mark_running(app, replay.json()["id"])
        again = await post_note(client, PH_CASE.patient_id, "pt resting", key="tap-1")
        assert again.status_code == 202
        assert len(queue.sent) == 1  # a running job is never sent again


@pytest.mark.asyncio
async def test_try_again_sends_the_message_a_failed_send_left_unsent(
    database_url: str, clock: MutableClock
) -> None:
    async with (
        running_app(database_url, clock) as app,
        client_for(app) as client,
    ):
        queue = FlakyQueue()
        app.state.queue = queue
        await sign_in(client, PH_STAFF)
        failed = await post_note(client, PH_CASE.patient_id, "pt resting", key="tap-1")
        assert failed.status_code == 500
        assert queue.sent == []
        detail = (await client.get(f"/api/v1/patients/{PH_CASE.patient_id}")).json()
        rough_id = detail["notes"][0]["job"]["rough_note_id"]

        tapped = await client.post(draft_path(rough_id))
        assert tapped.status_code == 202, tapped.text
        assert queue.sent == [UUID(tapped.json()["id"])]

        await mark_running(app, tapped.json()["id"])
        await client.post(draft_path(rough_id))
        assert len(queue.sent) == 1
