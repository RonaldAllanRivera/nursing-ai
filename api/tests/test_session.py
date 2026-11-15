"""Signing in as a demo persona: the cookie, the shift in progress and the admin's empty session."""

from datetime import datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from nursing_core.demo import DEMO_PERSONAS

from .helpers import ADMIN, NOW, PH_STAFF, US_STAFF, MutableClock, client_for, running_app, sign_in

SESSION = "/api/v1/session"


def shift_of(response: httpx.Response) -> dict[str, str]:
    shift: dict[str, str] = response.json()["shift"]
    return shift


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("app_env", "secure"), [("dev", False), ("test", False), ("demo", True), ("prod", True)]
)
async def test_session_cookie_secure_only_in_demo_and_prod(
    database_url: str, clock: MutableClock, app_env: str, secure: bool
) -> None:
    async with running_app(database_url, clock, app_env) as app, client_for(app) as client:
        response = await client.post(SESSION, json={"persona_id": str(PH_STAFF)})
    assert response.status_code == 201
    cookie = response.headers["set-cookie"].lower()
    assert cookie.startswith("sl_session=")
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "path=/" in cookie
    assert "max-age=43200" in cookie
    assert ("secure" in cookie.split("; ")) is secure


@pytest.mark.asyncio
async def test_unknown_persona_is_404(client: httpx.AsyncClient) -> None:
    response = await client.post(SESSION, json={"persona_id": str(uuid4())})
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "not_found"
    assert "set-cookie" not in response.headers


@pytest.mark.asyncio
async def test_no_session_is_401_problem(client: httpx.AsyncClient) -> None:
    response = await client.get(SESSION)
    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "not_signed_in"


@pytest.mark.asyncio
async def test_a_cookie_that_names_no_session_is_401(client: httpx.AsyncClient) -> None:
    client.cookies.set("sl_session", "not-a-real-token")
    response = await client.get(SESSION)
    assert response.status_code == 401
    assert response.json()["code"] == "not_signed_in"


@pytest.mark.asyncio
async def test_expired_session_is_401(client: httpx.AsyncClient, clock: MutableClock) -> None:
    await sign_in(client, PH_STAFF)
    clock.advance(timedelta(hours=12, seconds=1))
    assert (await client.get(SESSION)).status_code == 401


@pytest.mark.asyncio
async def test_personas_need_no_session_and_name_the_facility(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/personas")
    assert response.status_code == 200
    found = {item["id"]: item for item in response.json()}
    assert set(found) == {str(persona.id) for persona in DEMO_PERSONAS}
    assert found[str(PH_STAFF)]["facility_name"] == "SYNTHETIC Demo Hospital (PH)"
    assert found[str(US_STAFF)]["facility_key"] == "us-demo"
    assert found[str(ADMIN)]["facility_name"] is None
    assert found[str(ADMIN)]["role"] == "admin"


@pytest.mark.asyncio
async def test_sign_in_returns_the_session_and_get_reads_it_back(
    client: httpx.AsyncClient,
) -> None:
    created = await sign_in(client, PH_STAFF)
    read = await client.get(SESSION)
    assert read.status_code == 200
    assert read.json() == created.json()
    assert created.json()["user_id"] == str(PH_STAFF)
    assert created.json()["role"] == "staff_nurse"
    assert created.json()["facility_key"] == "ph-demo"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("persona", "local_time", "code"),
    [
        (PH_STAFF, "2026-11-12T08:00:00+08:00", "6-2"),
        (PH_STAFF, "2026-11-12T13:40:00+08:00", "2-10"),  # the 2-10 starts within 30 minutes
        (PH_STAFF, "2026-11-12T14:10:00+08:00", "2-10"),
        (PH_STAFF, "2026-11-12T05:10:00+08:00", "10-6"),
        (US_STAFF, "2026-11-12T13:00:00-08:00", "7a-7p"),
        (US_STAFF, "2026-11-12T20:00:00-08:00", "7p-7a"),
    ],
)
async def test_session_starts_on_the_nearest_shift(
    client: httpx.AsyncClient, clock: MutableClock, persona: UUID, local_time: str, code: str
) -> None:
    clock.set(datetime.fromisoformat(local_time))
    created = await sign_in(client, persona)
    assert shift_of(created)["code"] == code


@pytest.mark.asyncio
async def test_shift_change_outside_the_choices_is_422(client: httpx.AsyncClient) -> None:
    await sign_in(client, PH_STAFF)
    before = shift_of(await client.get(SESSION))
    # The 6-2 on the next day is two shifts after the current one: not a choice.
    response = await client.put(f"{SESSION}/shift", json={"starts_at": "2026-11-13T06:00:00+08:00"})
    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["code"] == "invalid_request"
    assert [error["field"] for error in body["errors"]] == ["body.starts_at"]
    assert shift_of(await client.get(SESSION)) == before


@pytest.mark.asyncio
async def test_shift_change_to_the_next_or_previous_shift_is_kept(
    client: httpx.AsyncClient,
) -> None:
    await sign_in(client, PH_STAFF)
    # 08:00 Manila is the 6-2; the choices are 10-6 (yesterday), 6-2 and 2-10.
    after = await client.put(f"{SESSION}/shift", json={"starts_at": "2026-11-12T06:00:00Z"})
    assert after.status_code == 200
    assert shift_of(after)["code"] == "2-10"
    assert shift_of(await client.get(SESSION))["code"] == "2-10"
    earlier = await client.put(f"{SESSION}/shift", json={"starts_at": "2026-11-11T14:00:00+00:00"})
    assert earlier.status_code == 200
    assert shift_of(earlier)["code"] == "10-6"


@pytest.mark.asyncio
async def test_shift_change_needs_a_session(client: httpx.AsyncClient) -> None:
    response = await client.put(f"{SESSION}/shift", json={"starts_at": "2026-11-12T06:00:00Z"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_admin_session_has_no_facility_or_shift(client: httpx.AsyncClient) -> None:
    created = await sign_in(client, ADMIN)
    assert created.json()["facility_key"] is None
    assert created.json()["shift"] is None
    assert created.json()["role"] == "admin"
    assert (await client.get(SESSION)).json() == created.json()


@pytest.mark.asyncio
async def test_admin_cannot_change_shift(client: httpx.AsyncClient) -> None:
    await sign_in(client, ADMIN)
    response = await client.put(f"{SESSION}/shift", json={"starts_at": "2026-11-12T06:00:00Z"})
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


@pytest.mark.asyncio
async def test_sign_out_clears_the_cookie_and_the_row(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    await sign_in(client, PH_STAFF)
    token = client.cookies["sl_session"]
    assert await app.state.sessions.get(token, NOW) is not None
    response = await client.delete(SESSION)
    assert response.status_code == 204
    assert response.content == b""
    cleared = response.headers["set-cookie"].lower()
    assert cleared.startswith('sl_session="";') or cleared.startswith("sl_session=;")
    assert "max-age=0" in cleared
    assert await app.state.sessions.get(token, NOW) is None
    client.cookies.set("sl_session", token)
    assert (await client.get(SESSION)).status_code == 401


@pytest.mark.asyncio
async def test_sign_out_without_a_session_is_still_204(client: httpx.AsyncClient) -> None:
    response = await client.delete(SESSION)
    assert response.status_code == 204
