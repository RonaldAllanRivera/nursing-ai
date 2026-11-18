"""Where draft jobs go: one port, and the factory that picks the queue for this deployment."""

from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable
from uuid import UUID

from nursing_core.storage.repositories import PgNoteRepository

from nursing_api.aws.sqs import SqsDraftJobQueue
from nursing_api.settings import Settings
from nursing_api.worker import InProcessQueue


@runtime_checkable
class ManagedQueue(Protocol):
    """A draft-job queue the app starts and stops: core's `DraftJobQueue` plus its lifecycle."""

    async def enqueue(self, job_id: UUID) -> None: ...

    async def start(self, wait_seconds: float) -> None:
        """Runs once at startup (the in-process queue recovers jobs a crash left behind)."""
        ...

    async def close(self) -> None: ...


class IdleQueue:
    """For the worker and ops roles when no queue URL is set: they run jobs, never enqueue them,
    and must not run the in-process recovery (it would fail jobs another worker is running)."""

    async def enqueue(self, job_id: UUID) -> None:
        raise RuntimeError("this role does not enqueue draft jobs")

    async def start(self, wait_seconds: float) -> None:
        del wait_seconds

    async def close(self) -> None:
        return None


def build_queue(
    settings: Settings, run: Callable[[UUID], Awaitable[None]], notes: PgNoteRepository
) -> ManagedQueue:
    """SQS when `DRAFT_QUEUE_URL` is set; else the in-process queue for the API; else (the
    worker and ops roles) one that never enqueues."""
    if settings.draft_queue_url:
        return SqsDraftJobQueue(settings.draft_queue_url)
    if settings.app_role == "api":
        return InProcessQueue(run, notes)
    return IdleQueue()
