"""Drafts on SQS: the queue sends one message per job. boto3 runs only behind a Stubber."""

import json
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from botocore.stub import Stubber
from nursing_api.aws import sqs
from nursing_api.aws.clients import dual_stack_client
from nursing_api.aws.sqs import SqsDraftJobQueue
from nursing_api.queue import build_queue
from nursing_api.settings import Settings
from nursing_core.demo import load_demo_cases
from nursing_core.domain.jobs import JobStatus
from types_boto3_sqs import SQSClient

from .helpers import PH_STAFF, MutableClock, running_app

QUEUE_URL = "https://sqs.ap-southeast-2.api.aws/123456789012/nursing-ai-drafts"
REGION = "ap-southeast-2"
PH_CASE = next(case for case in load_demo_cases() if case.facility_key == "ph-demo")


@pytest.fixture(autouse=True)
def fake_aws(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Fake credentials and an empty config, so boto3 never reads a real profile."""
    empty = tmp_path / "empty"
    empty.write_text("")
    for name in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE", "AWS_SESSION_TOKEN", "AWS_ENDPOINT_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_CONFIG_FILE", str(empty))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(empty))
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)


@pytest.fixture
def stubbed(monkeypatch: pytest.MonkeyPatch) -> Iterator[Stubber]:
    """The queue's client factory, patched to a Stubber'd client."""
    client: SQSClient = dual_stack_client("sqs")
    stubber = Stubber(client)
    monkeypatch.setattr(sqs, "make_client", lambda: client)
    with stubber:
        yield stubber


@pytest.mark.asyncio
async def test_enqueue_sends_one_message_with_the_job_id(stubbed: Stubber) -> None:
    job_id = uuid4()
    stubbed.add_response(
        "send_message",
        {"MessageId": "m-1", "MD5OfMessageBody": "0" * 32},
        {"QueueUrl": QUEUE_URL, "MessageBody": json.dumps({"job_id": str(job_id)})},
    )

    await SqsDraftJobQueue(QUEUE_URL).enqueue(job_id)

    stubbed.assert_no_pending_responses()


@pytest.mark.asyncio
async def test_start_and_close_make_no_aws_call(stubbed: Stubber) -> None:
    queue = SqsDraftJobQueue(QUEUE_URL)
    await queue.start(1.0)
    await queue.close()
    stubbed.assert_no_pending_responses()  # a call with no queued response would have raised


@pytest.mark.asyncio
async def test_a_queue_url_builds_the_sqs_queue(stubbed: Stubber) -> None:
    del stubbed

    async def never_run(job_id: UUID) -> None:
        raise AssertionError("not run")

    settings = Settings(
        database_url="postgresql+asyncpg://u@localhost/u", draft_queue_url=QUEUE_URL
    )
    assert isinstance(build_queue(settings, never_run, None), SqsDraftJobQueue)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_api_on_sqs_never_fails_running_jobs_at_startup(
    database_url: str, clock: MutableClock, stubbed: Stubber
) -> None:
    async with running_app(database_url, clock, draft_queue_url=QUEUE_URL) as app:
        record = await app.state.patients.get_patient(PH_CASE.patient_id)
        rough = PH_CASE.rough_note.model_copy(
            update={"id": uuid4(), "author_id": PH_STAFF, "encounter_id": record.encounter_id}
        )
        _, job = await app.state.notes.add_rough_note(rough, "key-1", "a" * 64)
        assert await app.state.notes.claim_job(job.id) is not None

    async with running_app(database_url, clock, draft_queue_url=QUEUE_URL) as restarted:
        assert (await restarted.state.notes.get_job(job.id)).status is JobStatus.RUNNING
    stubbed.assert_no_pending_responses()
