"""Where draft jobs go: one port, and the factory that picks the queue for this deployment."""

from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable
from uuid import UUID

from nursing_core.storage.repositories import PgNoteRepository

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


def build_queue(
    settings: Settings, run: Callable[[UUID], Awaitable[None]], notes: PgNoteRepository
) -> ManagedQueue:
    """The queue for these settings. For now, always the in-process one; the cloud lane sends to
    SQS when `DRAFT_QUEUE_URL` is set."""
    return InProcessQueue(run, notes)
