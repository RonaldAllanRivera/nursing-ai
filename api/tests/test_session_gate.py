"""The server enforces the session gate on every data route, and the CSRF token on every change."""

import json
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from nursing_api.logging import ALLOWED_KEYS
from nursing_core.storage import tables
from sqlalchemy import update

from .helpers import ADMIN, PH_STAFF, US_STAFF, MutableClock, client_for, keep_open, sign_in

SESSION = "/api/v1/session"
PATIENTS = "/api/v1/patients"
POLL = f"/api/v1/draft-jobs/{uuid4()}"
SHIFT_BODY = {"starts_at": "2026-11-12T06:00:00Z"}


@pytest.mark.asyncio
async def test_patient_routes_are_423_until_the_pin_is_entered(
    client: httpx.AsyncClient,
) -> None:
    started = await client.post(SESSION, json={"persona_id": str(PH_STAFF)})
    assert started.status_code == 201
    assert started.json()["gate"] == "enter_pin"
    response = await client.get(PATIENTS)
    assert response.status_code == 423
    assert response.json()["code"] == "enter_pin"


@pytest.mark.asyncio
async def test_get_session_works_while_locked_and_names_the_gate(
    client: httpx.AsyncClient, clock: MutableClock
) -> None:
    await sign_in(client, PH_STAFF)
    clock.advance(timedelta(minutes=5))
    response = await client.get(SESSION)
    assert response.status_code == 200
    body = response.json()
    assert (body["gate"], body["kind"]) == ("idle_locked", "persona")
    assert (await client.get(PATIENTS)).json()["code"] == "idle_locked"
    # Reading the session while locked never wakes it.
    assert (await client.get(SESSION)).json()["gate"] == "idle_locked"
    await keep_open(client)
    assert (await client.get(SESSION)).json()["gate"] == "open"
    assert (await client.get(PATIENTS)).status_code == 200


@pytest.mark.asyncio
async def test_a_locked_session_can_still_sign_out(
    client: httpx.AsyncClient, clock: MutableClock
) -> None:
    await sign_in(client, PH_STAFF)
    clock.advance(timedelta(minutes=10))
    assert (await client.delete(SESSION)).status_code == 204


@pytest.mark.asyncio
async def test_open_requests_keep_the_session_awake(
    client: httpx.AsyncClient, clock: MutableClock
) -> None:
    await sign_in(client, PH_STAFF)
    for _ in range(3):
        clock.advance(timedelta(minutes=4))
        assert (await client.get(PATIENTS)).status_code == 200


@pytest.mark.asyncio
async def test_polling_a_draft_job_does_not_keep_the_session_awake(
    client: httpx.AsyncClient, clock: MutableClock
) -> None:
    await sign_in(client, PH_STAFF)
    clock.advance(timedelta(minutes=4))
    assert (await client.get(POLL)).status_code == 404  # open: the job simply is not there
    clock.advance(timedelta(minutes=1))
    assert (await client.get(POLL)).status_code == 423  # five minutes since the last real use


@pytest.mark.asyncio
async def test_idle_exactly_at_the_limit_locks_on_the_server(
    client: httpx.AsyncClient, clock: MutableClock
) -> None:
    await sign_in(client, PH_STAFF)
    clock.advance(timedelta(minutes=5) - timedelta(seconds=1))
    assert (await client.get(PATIENTS)).status_code == 200
    clock.advance(timedelta(minutes=5))
    assert (await client.get(PATIENTS)).status_code == 423


@pytest.mark.asyncio
async def test_unsafe_request_without_csrf_header_is_403(client: httpx.AsyncClient) -> None:
    await sign_in(client, PH_STAFF)
    del client.headers["X-CSRF-Token"]
    for response in (
        await client.put(f"{SESSION}/shift", json=SHIFT_BODY),
        await client.patch(f"/api/v1/notes/{uuid4()}/lines/x", json={}),
        await client.delete(SESSION),
    ):
        assert response.status_code == 403
        assert response.json()["code"] == "csrf_failed"
    assert (await client.get(SESSION)).status_code == 200  # the session lives on


@pytest.mark.asyncio
async def test_csrf_beats_the_gate(client: httpx.AsyncClient, clock: MutableClock) -> None:
    await sign_in(client, PH_STAFF)
    clock.advance(timedelta(minutes=10))
    client.headers["X-CSRF-Token"] = "wrong"
    response = await client.put(f"{SESSION}/shift", json=SHIFT_BODY)
    assert (response.status_code, response.json()["code"]) == (403, "csrf_failed")
    del client.headers["X-CSRF-Token"]
    response = await client.post(f"{PATIENTS}/{uuid4()}/rough-notes", json={})
    assert (response.status_code, response.json()["code"]) == (403, "csrf_failed")


@pytest.mark.asyncio
async def test_csrf_from_another_session_is_403(app: FastAPI) -> None:
    async with client_for(app) as first, client_for(app) as second:
        await sign_in(first, PH_STAFF)
        await sign_in(second, US_STAFF)
        first.headers["X-CSRF-Token"] = second.headers["X-CSRF-Token"]
        response = await first.delete(SESSION)
    assert response.status_code == 403
    assert response.json()["code"] == "csrf_failed"


@pytest.mark.asyncio
async def test_sign_out_with_a_live_session_ends_it_with_the_token(
    client: httpx.AsyncClient,
) -> None:
    await sign_in(client, PH_STAFF)
    assert (await client.delete(SESSION)).status_code == 204
    assert (await client.get(SESSION)).status_code == 401


@pytest.mark.asyncio
async def test_expired_session_is_401_even_when_locked(
    client: httpx.AsyncClient, clock: MutableClock
) -> None:
    await sign_in(client, PH_STAFF)
    clock.advance(timedelta(hours=13))
    for response in (await client.get(SESSION), await client.get(PATIENTS)):
        assert response.status_code == 401
        assert response.json()["code"] == "not_signed_in"
    # No session, no token to check: a change is 401 too.
    assert (await client.put(f"{SESSION}/shift", json=SHIFT_BODY)).status_code == 401


@pytest.mark.asyncio
async def test_the_role_check_comes_after_the_gate(
    client: httpx.AsyncClient, clock: MutableClock
) -> None:
    await sign_in(client, ADMIN)
    assert (await client.put(f"{SESSION}/shift", json=SHIFT_BODY)).status_code == 403
    clock.advance(timedelta(minutes=10))
    assert (await client.put(f"{SESSION}/shift", json=SHIFT_BODY)).status_code == 423


@pytest.mark.asyncio
async def test_a_revoked_user_is_401_at_any_gate(client: httpx.AsyncClient, app: FastAPI) -> None:
    await sign_in(client, PH_STAFF)
    async with app.state.engine.begin() as conn:
        await conn.execute(
            update(tables.app_user)
            .where(tables.app_user.c.id == PH_STAFF)
            .values(revoked_at=app.state.clock.now())
        )
    for response in (await client.get(SESSION), await client.get(PATIENTS)):
        assert (response.status_code, response.json()["code"]) == (401, "not_signed_in")


@pytest.mark.asyncio
async def test_session_kind_is_google_for_an_invited_user(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    await sign_in(client, PH_STAFF)
    async with app.state.engine.begin() as conn:
        await conn.execute(
            update(tables.app_user)
            .where(tables.app_user.c.id == PH_STAFF)
            .values(persona=False, email="nurse@example.com", pin_hash=None)
        )
    body = (await client.get(SESSION)).json()
    assert (body["kind"], body["gate"]) == ("google", "set_pin")


@pytest.mark.asyncio
async def test_a_refused_csrf_is_logged_with_ids_only(
    client: httpx.AsyncClient, capfd: pytest.CaptureFixture[str]
) -> None:
    await sign_in(client, PH_STAFF)
    token = client.headers["X-CSRF-Token"]
    client.headers["X-CSRF-Token"] = "not-the-token"
    await client.delete(SESSION)
    out = capfd.readouterr().out
    events = [json.loads(line) for line in out.splitlines() if line.startswith("{")]
    refused = [e for e in events if e.get("event") == "security.csrf_failed"]
    assert len(refused) == 1
    assert refused[0]["user_id"] == str(PH_STAFF)
    assert set(refused[0]) <= ALLOWED_KEYS
    assert token not in out
    assert "not-the-token" not in out
