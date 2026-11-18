"""The ops function's tasks: migrate, seed the demo, and smoke-check every outbound dependency.

The ops Lambda sits in the VPC, which has IPv6 egress only. `smoke` therefore resolves each host's
AAAA records alone and fails a dependency that has none or that connects over IPv4. The network
parts live behind `Network` and the database check is a function, so tests inject fakes.

Logs carry the task, the dependency and an error class, never a value or a driver's message.
"""

from __future__ import annotations

import asyncio
import http.client
import ipaddress
import os
import socket
import ssl
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol
from urllib.parse import urlsplit

import structlog
from nursing_core.ports import Clock
from nursing_core.storage.migrate import upgrade
from nursing_core.storage.seed import seed
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from nursing_api.aws.clients import dual_stack_client
from nursing_api.settings import Settings

if TYPE_CHECKING:  # the stubs are a dev dependency: never imported at run time
    from types_boto3_sqs import SQSClient
    from types_boto3_ssm import SSMClient

log = structlog.get_logger("nursing_api.ops")

TASKS = ("migrate", "seed-demo", "smoke")
GOOGLE_HOST = "accounts.google.com"
GOOGLE_DISCOVERY = f"https://{GOOGLE_HOST}/.well-known/openid-configuration"
ANTHROPIC_HOST = "api.anthropic.com"
TIMEOUT_S = 10.0


@dataclass(frozen=True)
class OpsResult:
    """What the route answers: the task, whether it worked, and the names of what failed."""

    task: str
    ok: bool
    failed: list[str] = field(default_factory=list[str])
    refused: bool = False


class Network(Protocol):
    """The outbound network, IPv6 only. Tests replace it."""

    def resolve_ipv6(self, host: str) -> list[str]:
        """The host's AAAA addresses; raises OSError when it has none."""
        ...

    def tls_handshake(self, host: str) -> str:
        """Connect to `host:443` over IPv6, complete a TLS handshake, return the peer address."""
        ...

    def get_status(self, url: str) -> int:
        """GET `url` over IPv6 and return the HTTP status."""
        ...


class Ipv6Network:
    def resolve_ipv6(self, host: str) -> list[str]:
        infos = socket.getaddrinfo(host, 443, socket.AF_INET6, socket.SOCK_STREAM)
        addresses = [str(info[4][0]) for info in infos]
        if not addresses:
            raise OSError("no IPv6 address")
        return addresses

    def tls_handshake(self, host: str) -> str:
        address = self.resolve_ipv6(host)[0]
        context = ssl.create_default_context()
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as raw:
            raw.settimeout(TIMEOUT_S)
            raw.connect((address, 443))
            with context.wrap_socket(raw, server_hostname=host) as tls:
                return str(tls.getpeername()[0])

    def get_status(self, url: str) -> int:
        parts = urlsplit(url)
        connection = _Ipv6HttpsConnection(parts.hostname or "", timeout=TIMEOUT_S)
        try:
            connection.request("GET", parts.path or "/")
            return connection.getresponse().status
        finally:
            connection.close()


class _Ipv6HttpsConnection(http.client.HTTPSConnection):
    """An HTTPS connection that connects over IPv6 only (httpx is a dev dependency)."""

    def connect(self) -> None:
        network = Ipv6Network()
        raw = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        raw.settimeout(self.timeout if isinstance(self.timeout, float) else TIMEOUT_S)
        raw.connect((network.resolve_ipv6(self.host)[0], self.port))
        self.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=self.host)


def _require_ipv6_peer(address: str) -> None:
    if ipaddress.ip_address(address).version != 6:
        raise OSError("connected over IPv4")


class Ops:
    """Runs one ops task. The arguments after `clock` are test seams; each has a real default."""

    def __init__(
        self,
        settings: Settings,
        engine: AsyncEngine,
        clock: Clock,
        *,
        network: Network | None = None,
        ssm: SSMClient | None = None,
        sqs: SQSClient | None = None,
        environ: Mapping[str, str] | None = None,
        check_database: Callable[[], Awaitable[None]] | None = None,
        upgrade: Callable[[str], Awaitable[None]] = upgrade,
        seed: Callable[[AsyncEngine, Clock], Awaitable[None]] = seed,
    ) -> None:
        self._settings = settings
        self._engine = engine
        self._clock = clock
        self._network: Network = network if network is not None else Ipv6Network()
        self._ssm = ssm
        self._sqs = sqs
        self._environ = environ if environ is not None else os.environ
        self._check_database = check_database or self._ping_database
        self._upgrade = upgrade
        self._seed = seed

    async def run(self, task: str) -> OpsResult:
        """Run `task` (one of TASKS) and say how it went."""
        if task == "smoke":
            return await self._smoke()
        if task == "seed-demo" and self._settings.app_env != "demo":
            log.warning("ops task refused", task=task)
            return OpsResult(task, ok=False, failed=[task], refused=True)
        if task == "migrate":
            return await self._guarded(task, self._upgrade(self._settings.database_url))
        if task == "seed-demo":
            return await self._guarded(task, self._seed(self._engine, self._clock))
        raise ValueError("unknown ops task")

    async def _guarded(self, task: str, work: Awaitable[None]) -> OpsResult:
        try:
            await work
        except Exception as error:  # answered as a failed task, class only logged
            log.error("ops task failed", task=task, error_class=type(error).__name__)
            return OpsResult(task, ok=False, failed=[task])
        log.info("ops task done", task=task)
        return OpsResult(task, ok=True)

    async def _smoke(self) -> OpsResult:
        checks: list[tuple[str, Callable[[], Awaitable[None]]]] = [
            ("database", self._check_database),
            ("google", self._google),
            ("anthropic", self._anthropic),
            ("ssm", self._ssm_parameter),
            ("sqs", self._sqs_queue),
        ]
        failed: list[str] = []
        for dependency, check in checks:
            try:
                await check()
            except Exception as error:  # one failure must not hide the others
                log.error(
                    "smoke check failed",
                    task="smoke",
                    dependency=dependency,
                    error_class=type(error).__name__,
                )
                failed.append(dependency)
        if not failed:
            log.info("smoke passed", task="smoke")
        return OpsResult("smoke", ok=not failed, failed=failed)

    async def _ping_database(self) -> None:
        # Aurora sits inside the VPC and is IPv4: only the outbound dependencies need IPv6.
        async with self._engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def _google(self) -> None:
        await asyncio.to_thread(self._network.resolve_ipv6, GOOGLE_HOST)
        status = await asyncio.to_thread(self._network.get_status, GOOGLE_DISCOVERY)
        if status != 200:
            raise OSError("unexpected answer")

    async def _anthropic(self) -> None:
        peer = await asyncio.to_thread(self._network.tls_handshake, ANTHROPIC_HOST)
        _require_ipv6_peer(peer)

    async def _ssm_parameter(self) -> None:
        name = self._environ.get("SITE_URL_SSM_PARAMETER")
        if not name:
            raise KeyError("SITE_URL_SSM_PARAMETER")
        if self._ssm is None:
            self._ssm = dual_stack_client("ssm")
        client = self._ssm
        await asyncio.to_thread(self._network.resolve_ipv6, _host(client.meta.endpoint_url))
        await asyncio.to_thread(client.get_parameter, Name=name, WithDecryption=True)

    async def _sqs_queue(self) -> None:
        url = self._settings.draft_queue_url
        if not url:
            raise KeyError("DRAFT_QUEUE_URL")
        if self._sqs is None:
            self._sqs = dual_stack_client("sqs")
        client = self._sqs
        await asyncio.to_thread(self._network.resolve_ipv6, _host(client.meta.endpoint_url))
        await asyncio.to_thread(
            client.get_queue_attributes, QueueUrl=url, AttributeNames=["QueueArn"]
        )


def _host(endpoint_url: str) -> str:
    host = urlsplit(endpoint_url).hostname
    if not host:
        raise ValueError("the client has no endpoint host")
    return host
