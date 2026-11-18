"""The queue seam: which queue a deployment gets, and the in-process queue's concurrency limit."""

import asyncio
from uuid import UUID, uuid4

import pytest
from nursing_api.queue import IdleQueue, build_queue
from nursing_api.settings import Settings
from nursing_api.worker import InProcessQueue

DATABASE = "postgresql+asyncpg://u@localhost/u"


async def _unused(job_id: UUID) -> None:
    raise AssertionError("not run")


@pytest.mark.asyncio
async def test_in_process_queue_runs_at_most_two_jobs_at_once() -> None:
    running = 0
    peak = 0
    release = asyncio.Event()

    async def run(job_id: UUID) -> None:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await release.wait()
        running -= 1

    queue = InProcessQueue(run, None)  # type: ignore[arg-type]
    for _ in range(5):
        await queue.enqueue(uuid4())
    await asyncio.sleep(0.05)
    assert (running, queue.pending) == (2, 5)

    release.set()
    await queue.drain()
    assert peak == 2


@pytest.mark.parametrize("role", ["worker", "ops"])
@pytest.mark.asyncio
async def test_a_role_that_never_enqueues_gets_a_queue_that_refuses(role: str) -> None:
    queue = build_queue(Settings(database_url=DATABASE, app_role=role), _unused, None)  # type: ignore[arg-type]
    assert isinstance(queue, IdleQueue)
    await queue.start(1.0)  # no recovery, nothing happens
    await queue.close()
    with pytest.raises(RuntimeError):
        await queue.enqueue(uuid4())


def test_the_api_without_a_queue_url_runs_jobs_in_process() -> None:
    queue = build_queue(Settings(database_url=DATABASE), _unused, None)  # type: ignore[arg-type]
    assert isinstance(queue, InProcessQueue)
