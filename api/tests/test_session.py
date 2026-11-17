"""Signing in as a demo persona: the cookie, the shift in progress and the admin's empty session."""

import asyncio
import hashlib
import json
import secrets
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from nursing_api.logging import ALLOWED_KEYS
from nursing_core.auth.pins import MAX_PIN_TRIES, hash_pin, verify_pin
from nursing_core.demo import DEMO_PERSONAS, DEMO_PIN
from nursing_core.domain.users import Role
from nursing_core.storage import tables
from sqlalchemy import insert, select, update

from .helpers import ADMIN, NOW, PH_STAFF, US_STAFF, MutableClock, client_for, running_app, sign_in

SESSION = "/api/v1/session"


async def start(client: httpx.AsyncClient, persona_id: UUID) -> httpx.Response:
    """Signs in through the persona route itself (the shared helper writes its session directly)."""
    response = await client.post(SESSION, json={"persona_id": str(persona_id)})
    assert response.status_code == 201, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return response


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
async def test_session_answer_carries_its_csrf_token_gate_and_limits(
    client: httpx.AsyncClient, clock: MutableClock
) -> None:
    started = await client.post(SESSION, json={"persona_id": str(PH_STAFF)})
    body = started.json()
    assert (body["kind"], body["idle_lock_seconds"]) == ("persona", 300)
    # A persona has a PIN but has not typed it in this session yet.
    assert body["gate"] == "enter_pin"
    assert len(body["csrf_token"]) >= 43
    assert body["csrf_token"] not in started.headers["set-cookie"]
    assert datetime.fromisoformat(body["expires_at"]) == clock.now() + timedelta(hours=12)
    again = (await client.get(SESSION)).json()
    assert (again["csrf_token"], again["expires_at"]) == (body["csrf_token"], body["expires_at"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("persona", "hours"), [(PH_STAFF, 12), (US_STAFF, 14), (ADMIN, 12)], ids=["ph", "us", "admin"]
)
async def test_session_and_cookie_last_the_facilitys_hours(
    client: httpx.AsyncClient, clock: MutableClock, persona: UUID, hours: int
) -> None:
    response = await start(client, persona)

    assert f"max-age={hours * 3600}" in response.headers["set-cookie"].lower()
    expires = datetime.fromisoformat(response.json()["expires_at"])
    assert expires == clock.now() + timedelta(hours=hours)


@pytest.mark.asyncio
async def test_unknown_persona_is_404(client: httpx.AsyncClient) -> None:
    response = await client.post(SESSION, json={"persona_id": str(uuid4())})
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "not_found"
    assert "set-cookie" not in response.headers


@pytest.mark.asyncio
async def test_persona_sign_in_refuses_an_invited_user(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    # Only Google signs in an invited person: their id must not open a session here.
    invited = uuid4()
    async with app.state.engine.begin() as conn:
        facility = (
            await conn.execute(
                select(tables.facility.c.id).where(tables.facility.c.key == "ph-demo")
            )
        ).scalar_one()
        await conn.execute(
            insert(tables.app_user).values(
                id=invited,
                display_name="nurse.b@example.com",
                initials="NB",
                role="staff_nurse",
                facility_id=facility,
                email="nurse.b@example.com",
            )
        )
    response = await client.post(SESSION, json={"persona_id": str(invited)})
    assert response.status_code == 404
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
    created = await start(client, PH_STAFF)
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
    created = await start(client, persona)
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
    created = await start(client, ADMIN)
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


GOOGLE_PIN = "246813"
WRONG = "864209"
PIN, UNLOCK = f"{SESSION}/pin", f"{SESSION}/unlock"
PATIENTS = "/api/v1/patients"


async def google_admin(app: FastAPI, client: httpx.AsyncClient, *, pin: str | None) -> UUID:
    """An invited Google-kind admin (a row of its own) with an unverified session; `client`
    carries its cookie and CSRF token. Written through the tables, as `sign_in` does."""
    now: datetime = app.state.clock.now()
    user_id = uuid4()
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    async with app.state.engine.begin() as conn:
        await conn.execute(
            insert(tables.app_user).values(
                id=user_id,
                display_name="Gale Admin",
                initials="GA",
                role=Role.ADMIN.value,
                email=f"admin-{user_id.hex[:8]}@example.com",
                google_sub=f"sub-{user_id.hex}",
                pin_hash=None if pin is None else hash_pin(pin),
            )
        )
        await conn.execute(
            insert(tables.session).values(
                token_hash=hashlib.sha256(token.encode()).hexdigest(),
                user_id=user_id,
                created_at=now,
                expires_at=now + timedelta(hours=12),
                csrf_token=csrf,
                last_active_at=now,
            )
        )
    client.cookies.set("sl_session", token)
    client.headers["X-CSRF-Token"] = csrf
    return user_id


async def user_row(app: FastAPI, user_id: UUID) -> Any:
    async with app.state.engine.begin() as conn:
        return (
            await conn.execute(select(tables.app_user).where(tables.app_user.c.id == user_id))
        ).one()


def events(out: str, name: str) -> list[dict[str, Any]]:
    lines = [json.loads(line) for line in out.splitlines() if line.startswith("{")]
    return [line for line in lines if line.get("event") == name]


@pytest.mark.asyncio
async def test_set_pin_twice_is_409(app: FastAPI, client: httpx.AsyncClient) -> None:
    user_id = await google_admin(app, client, pin=None)
    assert (await client.get(SESSION)).json()["gate"] == "set_pin"

    first = await client.post(PIN, json={"pin": GOOGLE_PIN})
    second = await client.post(PIN, json={"pin": "975310"})

    assert first.status_code == 200, first.text
    assert (first.json()["gate"], first.json()["kind"]) == ("open", "google")
    assert (second.status_code, second.json()["code"]) == (409, "pin_already_set")
    stored = (await user_row(app, user_id)).pin_hash
    assert verify_pin(stored, GOOGLE_PIN)  # the second request changed nothing
    assert (await client.get("/api/v1/facilities")).status_code == 200  # the admin's data
    # A persona has a PIN too: 409 for her as well.
    async with client_for(app) as other:
        await start(other, PH_STAFF)
        refused = await other.post(PIN, json={"pin": GOOGLE_PIN})
    assert (refused.status_code, refused.json()["code"]) == (409, "pin_already_set")


@pytest.mark.asyncio
@pytest.mark.parametrize("pin", ["111111", "123456", "654321", "12345", "12345a", ""])
async def test_weak_pin_is_422_on_the_field(
    app: FastAPI, client: httpx.AsyncClient, pin: str
) -> None:
    user_id = await google_admin(app, client, pin=None)

    response = await client.post(PIN, json={"pin": pin})

    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "body.pin"
    assert (await user_row(app, user_id)).pin_hash is None
    assert (await client.get(SESSION)).json()["gate"] == "set_pin"


@pytest.mark.asyncio
async def test_unlock_with_the_right_pin_opens_the_session(
    app: FastAPI, client: httpx.AsyncClient, clock: MutableClock
) -> None:
    started = await start(client, PH_STAFF)
    assert (await client.get(PATIENTS)).status_code == 423

    unlocked = await client.post(UNLOCK, json={"pin": DEMO_PIN})

    assert unlocked.status_code == 200, unlocked.text
    assert unlocked.json()["gate"] == "open"
    assert unlocked.json()["expires_at"] == started.json()["expires_at"]  # never extended
    assert (await client.get(PATIENTS)).status_code == 200
    # After the idle lock the same PIN wakes it, and a wrong one before that still counts.
    clock.advance(timedelta(minutes=6))
    assert (await client.get(SESSION)).json()["gate"] == "idle_locked"
    wrong = await client.post(UNLOCK, json={"pin": WRONG})
    assert (wrong.status_code, wrong.json()["code"], wrong.json()["tries_left"]) == (
        403,
        "pin_wrong",
        4,
    )
    woken = await client.post(UNLOCK, json={"pin": DEMO_PIN})
    assert woken.json()["gate"] == "open"
    assert woken.json()["expires_at"] == started.json()["expires_at"]
    assert (await client.get(PATIENTS)).status_code == 200
    # The right PIN cleared the wrong try.
    session = await app.state.sessions.get(client.cookies["sl_session"], clock.now())
    assert session is not None
    assert session.pin_failures == 0


@pytest.mark.asyncio
async def test_unlock_refuses_the_gates_it_cannot_open(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    user_id = await google_admin(app, client, pin=None)
    refused = await client.post(UNLOCK, json={"pin": GOOGLE_PIN})
    assert (refused.status_code, refused.json()["code"]) == (423, "set_pin")
    async with app.state.engine.begin() as conn:
        await conn.execute(
            update(tables.app_user)
            .where(tables.app_user.c.id == user_id)
            .values(pin_hash=hash_pin(GOOGLE_PIN), pin_locked_at=app.state.clock.now())
        )
    locked = await client.post(UNLOCK, json={"pin": GOOGLE_PIN})
    assert (locked.status_code, locked.json()["code"]) == (423, "pin_locked")


@pytest.mark.asyncio
async def test_fifth_wrong_pin_locks_and_records_one_security_event(
    app: FastAPI, client: httpx.AsyncClient, capfd: pytest.CaptureFixture[str]
) -> None:
    user_id = await google_admin(app, client, pin=GOOGLE_PIN)

    answers = [await client.post(UNLOCK, json={"pin": WRONG}) for _ in range(MAX_PIN_TRIES)]

    assert [(a.status_code, a.json().get("tries_left")) for a in answers[:4]] == [
        (403, 4),
        (403, 3),
        (403, 2),
        (403, 1),
    ]
    assert (answers[4].status_code, answers[4].json()["code"]) == (423, "pin_locked")
    row = await user_row(app, user_id)
    assert row.pin_locked_at == app.state.clock.now()
    # Locked: even the right PIN opens nothing, and the session names the gate.
    right = await client.post(UNLOCK, json={"pin": GOOGLE_PIN})
    assert (right.status_code, right.json()["code"]) == (423, "pin_locked")
    assert (await client.get(SESSION)).json()["gate"] == "pin_locked"
    assert (await client.get(PATIENTS)).json()["code"] == "pin_locked"
    out = capfd.readouterr().out
    locked = events(out, "security.pin_locked")
    assert [e["user_id"] for e in locked] == [str(user_id)]
    failed = events(out, "security.pin_failed")
    assert [e["tries_left"] for e in failed] == [4, 3, 2, 1]
    assert all(set(e) <= ALLOWED_KEYS for e in [*locked, *failed])


@pytest.mark.asyncio
async def test_wrong_persona_pins_end_only_that_session(
    app: FastAPI, client: httpx.AsyncClient, clock: MutableClock
) -> None:
    await sign_in(client, PH_STAFF)
    async with client_for(app) as other:
        await sign_in(other, PH_STAFF)

        answers = [await other.post(UNLOCK, json={"pin": WRONG}) for _ in range(MAX_PIN_TRIES)]

        assert [a.status_code for a in answers] == [403, 403, 403, 403, 401]
        assert [a.json()["tries_left"] for a in answers[:4]] == [4, 3, 2, 1]
        assert answers[4].json()["code"] == "not_signed_in"
        cleared = answers[4].headers["set-cookie"].lower()
        assert cleared.startswith("sl_session=")
        assert "max-age=0" in cleared
        assert (await other.get(SESSION)).status_code == 401
    # The other session of the same persona is untouched, and so is her row.
    assert (await client.get(SESSION)).json()["gate"] == "open"
    assert (await client.get(PATIENTS)).status_code == 200
    row = await user_row(app, PH_STAFF)
    assert (row.pin_locked_at, row.pin_failures) == (None, 0)
    session = await app.state.sessions.get(client.cookies["sl_session"], clock.now())
    assert session is not None
    assert session.pin_failures == 0


@pytest.mark.asyncio
async def test_parallel_wrong_pins_never_verify_more_than_five(
    app: FastAPI,
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    user_id = await google_admin(app, client, pin=GOOGLE_PIN)
    verifies: list[str] = []

    def counting(pin_hash: str, pin: str) -> bool:
        verifies.append(pin)
        return verify_pin(pin_hash, pin)

    monkeypatch.setattr("nursing_api.auth.pin_check.verify_pin", counting)

    answers = await asyncio.gather(
        *(client.post(UNLOCK, json={"pin": WRONG}) for _ in range(MAX_PIN_TRIES * 3))
    )

    assert len(verifies) <= MAX_PIN_TRIES
    assert {a.status_code for a in answers} <= {403, 423}
    assert sum(a.json()["code"] == "pin_wrong" for a in answers) == MAX_PIN_TRIES - 1
    assert (await user_row(app, user_id)).pin_locked_at is not None
    assert len(events(capfd.readouterr().out, "security.pin_locked")) == 1
    # A right guess after the lock still verifies nothing.
    before = len(verifies)
    assert (await client.post(UNLOCK, json={"pin": GOOGLE_PIN})).status_code == 423
    assert len(verifies) == before


@pytest.mark.asyncio
async def test_pin_and_its_hash_never_in_logs_or_responses(
    app: FastAPI, client: httpx.AsyncClient, capfd: pytest.CaptureFixture[str]
) -> None:
    user_id = await google_admin(app, client, pin=None)
    token, csrf = client.cookies["sl_session"], client.headers["X-CSRF-Token"]
    answers = [
        await client.post(PIN, json={"pin": "111111"}),
        await client.post(PIN, json={"pin": GOOGLE_PIN}),
        await client.post(PIN, json={"pin": "975310"}),
        await client.post(UNLOCK, json={"pin": WRONG}),
        await client.post(UNLOCK, json={"pin": GOOGLE_PIN}),
    ]
    stored = (await user_row(app, user_id)).pin_hash
    for _ in range(MAX_PIN_TRIES):  # up to the lock, which logs its own event
        answers.append(await client.post(UNLOCK, json={"pin": WRONG}))
    captured = capfd.readouterr()
    logged = captured.out + captured.err
    for secret in (GOOGLE_PIN, WRONG, "975310", stored, "$argon2", csrf, token):
        assert secret not in logged
    for answer in answers:
        for secret in (GOOGLE_PIN, WRONG, "975310", stored, "$argon2", "111111", token):
            assert secret not in answer.text
        if not answer.is_success:  # only a session answer issues the CSRF token
            assert csrf not in answer.text


@pytest.mark.asyncio
async def test_an_exhausted_counter_heals_into_a_real_lock(
    app: FastAPI, client: httpx.AsyncClient, capfd: pytest.CaptureFixture[str]
) -> None:
    # The request that claimed the fifth try died before it could lock the account.
    user_id = await google_admin(app, client, pin=GOOGLE_PIN)
    async with app.state.engine.begin() as conn:
        await conn.execute(
            update(tables.app_user)
            .where(tables.app_user.c.id == user_id)
            .values(pin_failures=MAX_PIN_TRIES)
        )

    refused = await client.post(UNLOCK, json={"pin": GOOGLE_PIN})

    assert (refused.status_code, refused.json()["code"]) == (423, "pin_locked")
    assert (await user_row(app, user_id)).pin_locked_at is not None
    assert (await client.get(SESSION)).json()["gate"] == "pin_locked"
    assert len(events(capfd.readouterr().out, "security.pin_locked")) == 1


@pytest.mark.asyncio
async def test_a_right_pin_between_wrong_ones_never_locks_early(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    user_id = await google_admin(app, client, pin=GOOGLE_PIN)
    for _ in range(3):
        await client.post(UNLOCK, json={"pin": WRONG})
    assert (await client.post(UNLOCK, json={"pin": GOOGLE_PIN})).status_code == 200

    wrong = await client.post(UNLOCK, json={"pin": WRONG})

    assert (wrong.status_code, wrong.json()["tries_left"]) == (403, 4)
    assert (await user_row(app, user_id)).pin_locked_at is None
