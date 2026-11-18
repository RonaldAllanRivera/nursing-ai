"""The ops tasks: migrate, seed-demo and the smoke check. No test here reaches AWS or the net."""

from typing import Any
from unittest.mock import AsyncMock

import pytest
from botocore.stub import Stubber
from nursing_api.aws.clients import dual_stack_client
from nursing_api.ops import Ops
from nursing_api.settings import Settings
from nursing_core.clock import FixedClock
from sqlalchemy.ext.asyncio import create_async_engine
from types_boto3_sqs import SQSClient
from types_boto3_ssm import SSMClient

from .helpers import NOW
from .test_aws_ssm import fake_aws as fake_aws  # the autouse fixture

UNUSED = "postgresql+asyncpg://unused@db.example.com/unused"
QUEUE_URL = "https://sqs.ap-southeast-2.api.aws/123456789012/jobs"
SITE_PARAMETER = "/app/site"


class FakeNetwork:
    """Resolves and connects over IPv6 unless told otherwise; records what it was asked."""

    def __init__(self, *, no_ipv6: set[str] | None = None, ipv4_peer: set[str] | None = None):
        self.no_ipv6 = no_ipv6 or set()
        self.ipv4_peer = ipv4_peer or set()
        self.fetched: list[str] = []

    def resolve_ipv6(self, host: str) -> list[str]:
        if host in self.no_ipv6:
            raise OSError("no AAAA record")
        return ["2001:db8::1"]

    def tls_handshake(self, host: str) -> str:
        self.resolve_ipv6(host)
        return "203.0.113.7" if host in self.ipv4_peer else "2001:db8::1"

    def get_status(self, url: str) -> int:
        self.fetched.append(url)
        return 200


def stubbed_clients() -> tuple[SSMClient, SQSClient, Stubber, Stubber]:
    ssm = dual_stack_client("ssm")
    sqs = dual_stack_client("sqs")
    ssm_stub, sqs_stub = Stubber(ssm), Stubber(sqs)
    ssm_stub.add_response(
        "get_parameter",
        {"Parameter": {"Name": SITE_PARAMETER, "Value": "https://site.example.com"}},
        {"Name": SITE_PARAMETER, "WithDecryption": True},
    )
    sqs_stub.add_response(
        "get_queue_attributes",
        {"Attributes": {"QueueArn": "arn:aws:sqs:ap-southeast-2:123456789012:jobs"}},
        {"QueueUrl": QUEUE_URL, "AttributeNames": ["QueueArn"]},
    )
    ssm_stub.activate()
    sqs_stub.activate()
    return ssm, sqs, ssm_stub, sqs_stub


def make_ops(
    network: FakeNetwork,
    *,
    app_env: str = "demo",
    environ: dict[str, str] | None = None,
    queue_url: str | None = QUEUE_URL,
    **fakes: Any,
) -> tuple[Ops, Stubber, Stubber]:
    ssm, sqs, ssm_stub, sqs_stub = stubbed_clients()
    settings = Settings.model_validate(
        {
            "database_url": UNUSED,
            "app_role": "ops",
            "app_env": app_env,
            "draft_queue_url": queue_url,
        }
    )
    ops = Ops(
        settings,
        create_async_engine(UNUSED),
        FixedClock(NOW),
        network=network,
        ssm=ssm,
        sqs=sqs,
        environ={"SITE_URL_SSM_PARAMETER": SITE_PARAMETER} if environ is None else environ,
        check_database=fakes.pop("check_database", AsyncMock()),
        **fakes,
    )
    return ops, ssm_stub, sqs_stub


@pytest.mark.asyncio
async def test_smoke_passes_when_every_dependency_answers_over_ipv6() -> None:
    network = FakeNetwork()
    ops, ssm_stub, sqs_stub = make_ops(network)
    result = await ops.run("smoke")
    assert (result.ok, result.failed) == (True, [])
    ssm_stub.assert_no_pending_responses()
    sqs_stub.assert_no_pending_responses()
    assert network.fetched == ["https://accounts.google.com/.well-known/openid-configuration"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("dependency", "network"),
    [
        ("google", FakeNetwork(no_ipv6={"accounts.google.com"})),
        ("anthropic", FakeNetwork(no_ipv6={"api.anthropic.com"})),
        ("anthropic", FakeNetwork(ipv4_peer={"api.anthropic.com"})),
        ("ssm", FakeNetwork(no_ipv6={"ssm.ap-southeast-2.api.aws"})),
        ("sqs", FakeNetwork(no_ipv6={"sqs.ap-southeast-2.api.aws"})),
    ],
)
async def test_smoke_names_each_dependency_and_fails_on_ipv4(
    dependency: str, network: FakeNetwork
) -> None:
    ops, _, _ = make_ops(network)
    result = await ops.run("smoke")
    assert (result.ok, result.failed) == (False, [dependency])


@pytest.mark.asyncio
async def test_smoke_names_the_database_when_it_fails_and_the_rest_still_run() -> None:
    ops, _, _ = make_ops(FakeNetwork(), check_database=AsyncMock(side_effect=OSError("secret")))
    result = await ops.run("smoke")
    assert (result.ok, result.failed) == (False, ["database"])


@pytest.mark.asyncio
async def test_smoke_names_a_dependency_whose_setting_is_missing() -> None:
    ops, _, _ = make_ops(FakeNetwork(), environ={}, queue_url=None)
    result = await ops.run("smoke")
    assert result.failed == ["ssm", "sqs"]


@pytest.mark.asyncio
async def test_migrate_runs_the_upgrade_and_names_itself_on_failure() -> None:
    upgrade = AsyncMock()
    ops, _, _ = make_ops(FakeNetwork(), upgrade=upgrade)
    assert (await ops.run("migrate")).ok is True
    upgrade.assert_awaited_once_with(UNUSED)
    failing, _, _ = make_ops(FakeNetwork(), upgrade=AsyncMock(side_effect=RuntimeError("x")))
    result = await failing.run("migrate")
    assert (result.ok, result.failed) == (False, ["migrate"])


@pytest.mark.asyncio
async def test_seed_demo_runs_in_demo() -> None:
    seed = AsyncMock()
    ops, _, _ = make_ops(FakeNetwork(), seed=seed)
    assert (await ops.run("seed-demo")).ok is True
    seed.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("app_env", ["dev", "test", "prod"])
async def test_seed_demo_refused_outside_demo(app_env: str) -> None:
    seed = AsyncMock()
    ops, _, _ = make_ops(FakeNetwork(), app_env=app_env, seed=seed)
    result = await ops.run("seed-demo")
    assert (result.ok, result.failed, result.refused) == (False, ["seed-demo"], True)
    seed.assert_not_awaited()


@pytest.mark.asyncio
async def test_database_check_needs_no_ipv6_and_names_the_database_when_the_engine_fails(
    database_url: str,
) -> None:
    """Aurora is inside the VPC and IPv4: only the outbound dependencies must have IPv6."""
    network = FakeNetwork(no_ipv6={"localhost", "127.0.0.1", "db.example.com"})
    settings = Settings.model_validate(
        {"database_url": database_url, "app_role": "ops", "draft_queue_url": QUEUE_URL}
    )
    environ = {"SITE_URL_SSM_PARAMETER": SITE_PARAMETER}
    answers: dict[str, list[str]] = {}
    for name, url in (("up", database_url), ("down", "postgresql+asyncpg://u@127.0.0.1:1/x")):
        engine = create_async_engine(url, connect_args={"timeout": 2})
        ssm, sqs, _, _ = stubbed_clients()
        ops = Ops(
            settings, engine, FixedClock(NOW), network=network, ssm=ssm, sqs=sqs, environ=environ
        )
        answers[name] = (await ops.run("smoke")).failed
        await engine.dispose()
    assert answers == {"up": [], "down": ["database"]}
