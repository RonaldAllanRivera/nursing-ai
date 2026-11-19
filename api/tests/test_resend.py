"""A draft job whose message never reached a worker is sent again by the polls that look at it
(GET /draft-jobs/{id} and GET /patients/{id}), at most once a minute."""

import asyncio
from datetime import timedelta
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI

from .helpers import PH_STAFF, US_STAFF, MutableClock, client_for, post_note, sign_in
from .test_notes import PH_CASE

JOB = "/api/v1/draft-jobs/{}"
PATIENT = f"/api/v1/patients/{PH_CASE.patient_id}"


class LostQueue:
    """A queue whose messages go nowhere (or fail): the job stays `queued`."""

    def __init__(self) -> None:
        self.sent: list[UUID] = []
        self.fail = False

    async def enqueue(self, job_id: UUID) -> None:
        if self.fail:
            raise OSError("the send failed")
        self.sent.append(job_id)

    async def start(self, wait_seconds: float) -> None:
        del wait_seconds

    async def close(self) -> None:
        return None


async def stuck_job(app: FastAPI, client: httpx.AsyncClient) -> tuple[UUID, LostQueue]:
    """A rough note posted while every send is lost: one queued job, one send so far."""
    queue = LostQueue()
    app.state.queue = queue
    await sign_in(client, PH_STAFF)
    posted = await post_note(client, PH_CASE.patient_id, PH_CASE.rough_note.text)
    assert posted.status_code == 202, posted.text
    job_id = UUID(posted.json()["id"])
    assert queue.sent == [job_id]
    return job_id, queue


@pytest.mark.asyncio
async def test_polling_a_stuck_job_sends_it_again_once_a_minute(
    app: FastAPI, client: httpx.AsyncClient, clock: MutableClock
) -> None:
    job_id, queue = await stuck_job(app, client)

    await client.get(JOB.format(job_id))
    assert queue.sent == [job_id]  # polled at once: nothing to send yet

    clock.advance(timedelta(seconds=61))
    polled = await client.get(JOB.format(job_id))
    assert polled.status_code == 200
    assert polled.json()["status"] == "queued"
    assert queue.sent == [job_id, job_id]

    clock.advance(timedelta(seconds=30))
    await client.get(JOB.format(job_id))
    await client.get(PATIENT)
    assert queue.sent == [job_id, job_id]  # within the minute: no more

    clock.advance(timedelta(seconds=40))
    await client.get(JOB.format(job_id))
    assert queue.sent == [job_id] * 3


@pytest.mark.asyncio
async def test_opening_the_patient_sends_a_stuck_job_again(
    app: FastAPI, client: httpx.AsyncClient, clock: MutableClock
) -> None:
    job_id, queue = await stuck_job(app, client)
    clock.advance(timedelta(seconds=61))

    opened = await client.get(PATIENT)

    assert opened.status_code == 200
    assert [n["job"]["status"] for n in opened.json()["notes"]] == ["queued"]
    assert queue.sent == [job_id, job_id]


@pytest.mark.asyncio
async def test_two_polls_at_once_send_a_stuck_job_once(
    app: FastAPI, client: httpx.AsyncClient, clock: MutableClock
) -> None:
    job_id, queue = await stuck_job(app, client)
    clock.advance(timedelta(seconds=61))

    answers = await asyncio.gather(
        client.get(JOB.format(job_id)), client.get(JOB.format(job_id)), client.get(PATIENT)
    )

    assert [a.status_code for a in answers] == [200, 200, 200]
    assert queue.sent == [job_id, job_id]


@pytest.mark.asyncio
async def test_a_send_that_fails_never_breaks_the_poll_and_is_tried_a_minute_later(
    app: FastAPI, client: httpx.AsyncClient, clock: MutableClock
) -> None:
    job_id, queue = await stuck_job(app, client)
    queue.fail = True
    clock.advance(timedelta(seconds=61))

    assert (await client.get(JOB.format(job_id))).status_code == 200

    queue.fail = False
    clock.advance(timedelta(seconds=61))
    await client.get(JOB.format(job_id))
    assert queue.sent == [job_id, job_id]


@pytest.mark.asyncio
async def test_a_job_that_is_drafted_or_belongs_to_another_side_is_never_sent_again(
    app: FastAPI, client: httpx.AsyncClient, clock: MutableClock
) -> None:
    job_id, queue = await stuck_job(app, client)
    clock.advance(timedelta(seconds=61))
    async with client_for(app) as other:  # US staff: another facility
        await sign_in(other, US_STAFF)
        assert (await other.get(JOB.format(job_id))).status_code == 404
    assert queue.sent == [job_id]
