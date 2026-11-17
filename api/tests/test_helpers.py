"""The API tests' sign-in helper: an open session that sends its CSRF token.

Every lane's tests sign in through it, so they keep passing once the server enforces the PIN gate
and the CSRF check.
"""

import hashlib
from datetime import datetime, timedelta
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from nursing_core.storage import tables
from sqlalchemy import select

from .helpers import ADMIN, NOW, PH_STAFF, US_STAFF, sign_in


@pytest.mark.asyncio
async def test_helpers_session_is_open_and_sends_csrf(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    answer = await sign_in(client, PH_STAFF)
    token = client.cookies["sl_session"]
    async with app.state.engine.connect() as conn:
        row = (
            await conn.execute(
                select(tables.session).where(
                    tables.session.c.token_hash == hashlib.sha256(token.encode()).hexdigest()
                )
            )
        ).one()
    assert (row.pin_verified_at, row.last_active_at) == (NOW, NOW)
    assert answer.json()["gate"] == "open"
    assert answer.json()["csrf_token"] == row.csrf_token == client.headers["X-CSRF-Token"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("persona", "hours"), [(PH_STAFF, 12), (US_STAFF, 14), (ADMIN, 12)])
async def test_helpers_session_lasts_the_facilitys_hours(
    client: httpx.AsyncClient, persona: UUID, hours: int
) -> None:
    answer = await sign_in(client, persona)
    assert datetime.fromisoformat(answer.json()["expires_at"]) == NOW + timedelta(hours=hours)


@pytest.mark.asyncio
async def test_signing_in_again_replaces_the_cookie_and_the_csrf_token(
    client: httpx.AsyncClient,
) -> None:
    first = await sign_in(client, PH_STAFF)
    second = await sign_in(client, ADMIN)
    assert second.json()["role"] == "admin"
    assert client.headers["X-CSRF-Token"] == second.json()["csrf_token"]
    assert second.json()["csrf_token"] != first.json()["csrf_token"]
