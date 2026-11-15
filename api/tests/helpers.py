"""Helpers the API tests share: a clock the test can move, signing in, and the privacy check."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
from fastapi import FastAPI
from nursing_api.app import create_app
from nursing_api.settings import Settings
from nursing_core.demo import DemoCase

# The demo night: 08:00 in Manila (the 6-2 shift) and 16:00 the day before in Los Angeles (7a-7p).
NOW = datetime(2026, 11, 12, 0, 0, tzinfo=UTC)

PH_STAFF = UUID("00000000-0000-4000-8000-000000000101")
PH_HEAD = UUID("00000000-0000-4000-8000-000000000102")
US_STAFF = UUID("00000000-0000-4000-8000-000000000201")
US_HEAD = UUID("00000000-0000-4000-8000-000000000202")
ADMIN = UUID("00000000-0000-4000-8000-000000000901")
# The staff nurse of each facility, keyed by the facility's key.
STAFF_NURSE = {"ph-demo": PH_STAFF, "us-demo": US_STAFF}


class MutableClock:
    """A `Clock` whose time a test sets or moves (for example to a 6-2 session at 14:10)."""

    def __init__(self, at: datetime = NOW) -> None:
        self._at = at.astimezone(UTC)

    def now(self) -> datetime:
        return self._at

    def set(self, at: datetime) -> None:
        self._at = at.astimezone(UTC)

    def advance(self, delta: timedelta) -> None:
        self._at += delta


@asynccontextmanager
async def running_app(
    database_url: str, clock: MutableClock, app_env: str = "test"
) -> AsyncGenerator[FastAPI]:
    """The app with its lifespan running, on the given database and clock."""
    settings = Settings.model_validate({"database_url": database_url, "app_env": app_env})
    app = create_app(settings, clock=clock)
    async with app.router.lifespan_context(app):
        yield app


def client_for(app: FastAPI) -> httpx.AsyncClient:
    """A client that answers 500 for an unexpected error, as a server would, instead of raising."""
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def sign_in(client: httpx.AsyncClient, persona_id: UUID) -> httpx.Response:
    """Sign in as a demo persona; the client keeps the session cookie."""
    response = await client.post("/api/v1/session", json={"persona_id": str(persona_id)})
    assert response.status_code == 201, response.text
    return response


def _words(*names: str | None) -> set[str]:
    found: set[str] = set()
    for name in names:
        if name:
            found.add(name.lower())
            found.update(word for word in name.lower().split() if len(word) >= 3)
    return found


def forbidden_words(case: DemoCase) -> set[str]:
    """Lower-cased strings that must never appear in a log: the case's names and note text.

    That is every name word of the identity, the record number, address and postal code, and
    every 20-character window of the rough note (so no stretch of it can leak whole or in part).
    Extend the test that uses it as the API grows: post this note, sign that one.
    """
    identity = case.patient
    names = [
        identity.given_name,
        identity.middle_name,
        identity.family_name,
        identity.suffix,
        *identity.nicknames,
        *(relative.name for relative in identity.relatives),
    ]
    words = _words(*names, identity.record_number, identity.address, identity.postal_code)
    text = case.rough_note.text.lower()
    windows = {text[i : i + 20] for i in range(max(len(text) - 19, 1))}
    return words | windows
