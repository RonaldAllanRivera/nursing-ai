"""What a signed-out visitor is offered, and that asking never wakes the database."""

from typing import Any

import pytest
from nursing_api.app import create_app
from nursing_api.auth.google import AuthlibGoogleOidc
from nursing_api.settings import Settings
from nursing_core.demo import DEMO_PIN
from pydantic import SecretStr
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

from .fake_google import CLIENT_ID, CLIENT_SECRET, SITE_URL, START, FakeGoogle
from .helpers import PH_STAFF, MutableClock, client_for, running_app

OPTIONS = "/api/v1/sign-in-options"
PERSONAS = "/api/v1/personas"


@pytest.mark.asyncio
@pytest.mark.parametrize("app_env", ["dev", "demo", "prod"])
async def test_signed_out_routes_never_touch_the_database(free_port: int, app_env: Any) -> None:
    # A visitor or a crawler on the sign-in page must never wake a paused database: the options,
    # the persona list and the start of Google sign-in answer without opening a connection.
    url = f"postgresql+asyncpg://app:x@127.0.0.1:{free_port}/app"
    google = AuthlibGoogleOidc(CLIENT_ID, CLIENT_SECRET, transport=FakeGoogle().transport)
    app = create_app(
        Settings(
            database_url=url,
            app_env=app_env,
            site_url=SITE_URL,
            google_client_id=CLIENT_ID,
            google_client_secret=SecretStr(CLIENT_SECRET),
        ),
        google=google,
    )
    attempts: list[str] = []
    async with app.router.lifespan_context(app):
        engine: AsyncEngine = app.state.engine

        @event.listens_for(engine.sync_engine, "do_connect")
        def count(*_args: Any) -> None:  # pyright: ignore[reportUnusedFunction]
            attempts.append("connect")

        async with client_for(app) as client:
            options = await client.get(OPTIONS)
            personas = await client.get(PERSONAS)
            started = await client.get(START)
    assert options.status_code == 200
    assert options.json()["google"] is True
    assert personas.status_code == (404 if app_env == "prod" else 200)
    assert started.status_code == 302
    assert attempts == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("app_env", "personas", "demo", "pin"),
    [("dev", True, False, DEMO_PIN), ("demo", True, True, DEMO_PIN), ("prod", False, False, None)],
)
async def test_sign_in_options_follow_the_environment(
    database_url: str,
    clock: MutableClock,
    app_env: str,
    personas: bool,
    demo: bool,
    pin: str | None,
) -> None:
    async with running_app(database_url, clock, app_env) as app, client_for(app) as client:
        response = await client.get(OPTIONS)
    assert response.status_code == 200
    assert response.json() == {"google": False, "personas": personas, "demo": demo, "demo_pin": pin}


@pytest.mark.asyncio
async def test_personas_are_404_in_prod(database_url: str, clock: MutableClock) -> None:
    async with running_app(database_url, clock, "prod") as app, client_for(app) as client:
        listed = await client.get(PERSONAS)
        signed = await client.post("/api/v1/session", json={"persona_id": str(PH_STAFF)})
    assert (listed.status_code, listed.json()["code"]) == (404, "not_found")
    assert (signed.status_code, signed.json()["code"]) == (404, "not_found")
    assert "set-cookie" not in signed.headers
