"""The app's lifespan: it builds what the routes read from app.state, and disposes the engine."""

import subprocess
import sys
import time
from typing import Literal

import httpx
import pytest
from fastapi import FastAPI
from nursing_api.app import create_app
from nursing_api.auth.oidc import GoogleIdentity, GoogleOidc
from nursing_api.queue import ManagedQueue
from nursing_api.settings import Settings
from nursing_api.worker import InProcessQueue
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.pool import NullPool
from types_boto3_ssm import SSMClient

from .test_aws_ssm import fake_aws, ssm_with

__all__ = ["fake_aws"]  # the fixture, shared with test_aws_ssm


@pytest.mark.asyncio
async def test_lifespan_disposes_the_engine(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    disposed: list[AsyncEngine] = []
    real_dispose = AsyncEngine.dispose

    async def spy(self: AsyncEngine, close: bool = True) -> None:
        disposed.append(self)
        await real_dispose(self, close=close)

    monkeypatch.setattr(AsyncEngine, "dispose", spy)
    app = create_app(Settings(database_url=database_url))
    async with app.router.lifespan_context(app):
        engine = app.state.engine
        assert disposed == []
    assert disposed == [engine]


UNUSED = "postgresql+asyncpg://unused@localhost/unused"


async def status_of(app: FastAPI, method: str, path: str) -> int:
    # No lifespan runs here, so a built route that reads app.state fails: as a 500, which still
    # proves it is registered (only a missing route is a 404).
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return (await client.request(method, path, json={})).status_code


@pytest.mark.asyncio
@pytest.mark.parametrize(("role", "present"), [("api", False), ("worker", True), ("ops", True)])
async def test_events_route_absent_for_the_api_role(
    role: Literal["api", "worker", "ops"], present: bool
) -> None:
    app = create_app(Settings(database_url=UNUSED, app_role=role))
    assert (await status_of(app, "POST", "/events") != 404) is present


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("app_env", "present"), [("dev", False), ("demo", False), ("prod", False), ("test", True)]
)
async def test_the_test_sign_in_exists_only_in_test(
    app_env: Literal["dev", "test", "demo", "prod"], present: bool
) -> None:
    # Whatever the route answers once the auth lane builds it, elsewhere it is a 404.
    app = create_app(Settings(database_url=UNUSED, app_env=app_env))
    assert (await status_of(app, "POST", "/api/v1/test/session") != 404) is present


class StandInGoogle:
    """Satisfies the Google port without any network: the auth lane's FakeGoogle signs tokens."""

    def authorization_url(
        self, *, state: str, nonce: str, code_challenge: str, redirect_uri: str
    ) -> str:
        return f"https://accounts.example.com/o/auth?state={state}"

    async def exchange(self, *, code: str, code_verifier: str, redirect_uri: str) -> str:
        return "an-id-token"

    async def verify_id_token(self, id_token: str, *, nonce: str) -> GoogleIdentity:
        return GoogleIdentity(sub="1001", email="nurse@example.com", email_verified=True, name=None)


def test_create_app_takes_a_google_client() -> None:
    google: GoogleOidc = StandInGoogle()
    app = create_app(Settings(database_url=UNUSED), google=google)
    assert app.state.google is google


def test_without_google_settings_there_is_no_google_client() -> None:
    assert create_app(Settings(database_url=UNUSED)).state.google is None


@pytest.mark.asyncio
async def test_without_a_queue_url_drafts_run_in_process(database_url: str) -> None:
    app = create_app(Settings(database_url=database_url))
    async with app.router.lifespan_context(app):
        queue: ManagedQueue = app.state.queue
        assert isinstance(queue, InProcessQueue)


@pytest.mark.asyncio
@pytest.mark.parametrize(("pool", "null"), [("null", True), ("queue", False)])
async def test_lambda_settings_use_null_pool(
    database_url: str, pool: Literal["queue", "null"], null: bool
) -> None:
    app = create_app(Settings(database_url=database_url, db_pool=pool))
    async with app.router.lifespan_context(app):
        assert isinstance(app.state.engine.pool, NullPool) is null


@pytest.mark.asyncio
async def test_api_says_database_waking_when_the_connect_times_out(silent_port: int) -> None:
    settings = Settings(
        database_url=f"postgresql+asyncpg://app:x@127.0.0.1:{silent_port}/app",
        db_connect_timeout_s=0.5,
        db_ping_timeout_s=0.5,
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            client.cookies.set("sl_session", "made-up-token")
            started = time.monotonic()
            response = await client.get("/api/v1/session")
            elapsed = time.monotonic() - started
    assert elapsed < 2.0
    assert response.status_code == 503
    assert response.json()["code"] == "database_waking"
    assert response.headers["Retry-After"] == "5"


@pytest.mark.asyncio
@pytest.mark.usefixtures("fake_aws")
async def test_create_app_builds_settings_from_ssm(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no settings given, the real loader reads the named parameter through a stubbed client
    and the values SSM holds become the settings, over the environment."""
    client, stubber = ssm_with(("/app/database-url", database_url))
    monkeypatch.setenv("DATABASE_URL", UNUSED)
    monkeypatch.setenv("DATABASE_URL_SSM_PARAMETER", "/app/database-url")

    def stubbed(service: str) -> SSMClient:
        return client

    monkeypatch.setattr("nursing_api.aws.ssm.dual_stack_client", stubbed)
    app = create_app()
    async with app.router.lifespan_context(app):
        assert app.state.settings.database_url == database_url
    stubber.assert_no_pending_responses()


def test_app_imports_without_the_type_stubs() -> None:
    """The image installs no dev group, so `types_boto3_*` must never be needed at run time."""
    code = (
        "import sys\n"
        "class Block:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        '        if name.split(".")[0].startswith("types_boto3"):\n'
        "            raise ModuleNotFoundError(name)\n"
        "sys.meta_path.insert(0, Block())\n"
        "import nursing_api.app\n"
    )
    done = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code], capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr[-500:]
