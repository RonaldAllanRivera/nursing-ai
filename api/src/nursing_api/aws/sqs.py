"""The draft queue on SQS: one message per job, carrying only the job's id.

boto3 is synchronous, so each call runs in a thread. The worker Lambda reads the messages
(POST /events); nothing here receives or deletes them.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING
from uuid import UUID

from nursing_api.aws.clients import dual_stack_client

if TYPE_CHECKING:  # the stubs are a dev dependency: never imported at run time
    from types_boto3_sqs import SQSClient


def make_client() -> SQSClient:
    """The dual-stack SQS client. Tests patch this to hand the queue a stubbed one."""
    return dual_stack_client("sqs")


class SqsDraftJobQueue:
    """Implements core's `DraftJobQueue` and `ManagedQueue`. It never recovers jobs at startup:
    SQS redelivers, and the lease stops a job running twice."""

    def __init__(self, queue_url: str) -> None:
        self._queue_url = queue_url
        self._client: SQSClient | None = None

    async def enqueue(self, job_id: UUID) -> None:
        if self._client is None:
            self._client = make_client()  # once, on first use
        await asyncio.to_thread(
            self._client.send_message,
            QueueUrl=self._queue_url,
            MessageBody=json.dumps({"job_id": str(job_id)}),
        )

    async def start(self, wait_seconds: float) -> None:
        del wait_seconds

    async def close(self) -> None:
        return None
