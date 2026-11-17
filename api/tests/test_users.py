"""The staff list: who may list, invite, revoke and reset, and the test-only sign-in."""

import json
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from nursing_core.demo import DEMO_PERSONAS, DEMO_PIN
from nursing_core.domain.users import Role
from nursing_core.storage import tables
from sqlalchemy import select, update

from .fake_google import add_google_user
from .helpers import (
    ADMIN,
    MutableClock,
    client_for,
    running_app,
    sign_in,
)

USERS = "/api/v1/users"
PIN = "246813"
WRONG = "975310"
NEW = "new.nurse@example.com"


@asynccontextmanager
async def signed_in_as(
    app: FastAPI, email: str, role: Role, facility: str | None
) -> AsyncGenerator[httpx.AsyncClient]:
    """A real (non-persona) user written through the table, signed in with an open session."""
    user_id = await add_google_user(
        app, email, role, facility, pin=PIN, sub=f"sub-{email}", name=email.partition("@")[0]
    )
    async with client_for(app) as client:
        await sign_in(client, user_id)
        yield client


@pytest_asyncio.fixture
async def admin(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with signed_in_as(app, "real.admin@example.com", Role.ADMIN, None) as client:
        yield client


@pytest_asyncio.fixture
async def head(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with signed_in_as(app, "real.head@example.com", Role.HEAD_NURSE, "ph-demo") as client:
        yield client


def events(out: str, name: str) -> list[dict[str, Any]]:
    lines = [json.loads(line) for line in out.splitlines() if line.startswith("{")]
    return [line for line in lines if line.get("event") == name]


async def lock_pin(app: FastAPI, user_id: UUID) -> None:
    async with app.state.engine.begin() as conn:
        await conn.execute(
            update(tables.app_user)
            .where(tables.app_user.c.id == user_id)
            .values(pin_failures=5, pin_locked_at=app.state.clock.now())
        )


def requests_of(user_id: UUID) -> list[tuple[str, str, dict[str, Any] | None]]:
    return [
        ("GET", USERS, None),
        (
            "POST",
            USERS,
            {"email": NEW, "role": "staff_nurse", "facility_key": "ph-demo", "pin": PIN},
        ),
        ("POST", f"{USERS}/{user_id}/revoke", {"pin": PIN}),
        ("POST", f"{USERS}/{user_id}/pin-reset", {"pin": PIN}),
    ]


@pytest.mark.asyncio
async def test_staff_nurse_cannot_list_staff(app: FastAPI) -> None:
    async with signed_in_as(app, "real.nurse@example.com", Role.STAFF_NURSE, "ph-demo") as nurse:
        for method, path, body in requests_of(uuid4()):
            response = await nurse.request(method, path, json=body)
            assert response.status_code == 403, (method, path)
            assert response.json()["code"] == "forbidden"


@pytest.mark.asyncio
async def test_head_nurse_sees_only_her_facility(
    app: FastAPI, head: httpx.AsyncClient, admin: httpx.AsyncClient
) -> None:
    await add_google_user(app, "ph.nurse@example.com", Role.STAFF_NURSE, "ph-demo")
    await add_google_user(app, "us.nurse@example.com", Role.STAFF_NURSE, "us-demo")

    seen = (await head.get(USERS)).json()
    assert [u["email"] for u in seen] == ["ph.nurse@example.com", "real.head@example.com"]
    assert {u["facility_key"] for u in seen} == {"ph-demo"}
    assert set(seen[0]) == {
        "id", "email", "display_name", "initials", "role", "facility_key", "status", "pin_locked",
    }  # fmt: skip

    everyone = (await admin.get(USERS)).json()
    assert [u["email"] for u in everyone] == [
        "ph.nurse@example.com",
        "real.admin@example.com",
        "real.head@example.com",
        "us.nurse@example.com",
    ]


@pytest.mark.asyncio
async def test_invite_needs_the_admins_pin(
    admin: httpx.AsyncClient, capfd: pytest.CaptureFixture[str]
) -> None:
    body = {"email": NEW, "role": "staff_nurse", "facility_key": "ph-demo", "pin": WRONG}
    capfd.readouterr()
    refused = await admin.post(USERS, json=body)
    assert refused.status_code == 403
    assert refused.json()["code"] == "pin_wrong"
    assert NEW not in [u["email"] for u in (await admin.get(USERS)).json()]

    invited = await admin.post(USERS, json=body | {"pin": PIN})
    assert invited.status_code == 201
    assert invited.json()["status"] == "invited"
    assert invited.json()["facility_key"] == "ph-demo"
    assert (await admin.post(USERS, json=body | {"pin": PIN})).status_code == 409
    out = capfd.readouterr().out
    assert PIN not in out
    assert WRONG not in out
    assert NEW not in out


@pytest.mark.asyncio
async def test_invite_lowercases_the_email(admin: httpx.AsyncClient) -> None:
    response = await admin.post(
        USERS,
        json={
            "email": " New.Nurse@Example.com ",
            "role": "head_nurse",
            "facility_key": "us-demo",
            "pin": PIN,
        },
    )
    assert response.status_code == 201
    assert response.json()["email"] == NEW
    clash = await admin.post(
        USERS,
        json={
            "email": "NEW.NURSE@example.com",
            "role": "staff_nurse",
            "facility_key": "us-demo",
            "pin": PIN,
        },
    )
    assert clash.status_code == 409


@pytest.mark.asyncio
async def test_admin_cannot_revoke_themselves(app: FastAPI, admin: httpx.AsyncClient) -> None:
    me = (await admin.get("/api/v1/session")).json()["user_id"]
    response = await admin.post(f"{USERS}/{me}/revoke", json={"pin": PIN})
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"
    assert (await admin.get("/api/v1/session")).status_code == 200


@pytest.mark.asyncio
async def test_revoked_user_is_signed_out_and_kept(app: FastAPI, admin: httpx.AsyncClient) -> None:
    async with signed_in_as(app, "sam.nurse@example.com", Role.STAFF_NURSE, "us-demo") as sam:
        sam_id = (await sam.get("/api/v1/session")).json()["user_id"]
        wrong = await admin.post(f"{USERS}/{sam_id}/revoke", json={"pin": WRONG})
        assert wrong.status_code == 403
        assert (await sam.get("/api/v1/session")).status_code == 200

        response = await admin.post(f"{USERS}/{sam_id}/revoke", json={"pin": PIN})
        assert response.status_code == 200
        assert response.json()["status"] == "revoked"
        assert (await sam.get("/api/v1/session")).status_code == 401

    kept = [u for u in (await admin.get(USERS)).json() if u["id"] == sam_id]
    assert [u["status"] for u in kept] == ["revoked"]
    assert (await admin.post(f"{USERS}/{uuid4()}/revoke", json={"pin": PIN})).status_code == 404


@pytest.mark.asyncio
async def test_head_nurse_resets_a_nurses_pin_in_her_facility_only(
    app: FastAPI, head: httpx.AsyncClient, capfd: pytest.CaptureFixture[str]
) -> None:
    mine = await add_google_user(
        app, "ph.nurse@example.com", Role.STAFF_NURSE, "ph-demo", pin=PIN, sub="s1"
    )
    other = await add_google_user(
        app, "us.nurse@example.com", Role.STAFF_NURSE, "us-demo", pin=PIN, sub="s2"
    )
    await lock_pin(app, mine)
    await lock_pin(app, other)
    head_id = UUID((await head.get("/api/v1/session")).json()["user_id"])
    assert [u["pin_locked"] for u in (await head.get(USERS)).json() if u["id"] == str(mine)] == [
        True
    ]

    # Another facility's nurse, a persona and an unknown id look like no one: 404.
    assert (await head.post(f"{USERS}/{other}/pin-reset", json={"pin": PIN})).status_code == 404
    persona = DEMO_PERSONAS[0].id
    assert (await head.post(f"{USERS}/{persona}/pin-reset", json={"pin": PIN})).status_code == 404
    assert (await head.post(f"{USERS}/{uuid4()}/pin-reset", json={"pin": PIN})).status_code == 404
    # Herself is visible but refused.
    assert (await head.post(f"{USERS}/{head_id}/pin-reset", json={"pin": PIN})).status_code == 403
    # A head nurse never revokes or invites.
    assert (await head.post(f"{USERS}/{mine}/revoke", json={"pin": PIN})).status_code == 403

    capfd.readouterr()
    wrong = await head.post(f"{USERS}/{mine}/pin-reset", json={"pin": WRONG})
    assert wrong.status_code == 403
    assert wrong.json()["code"] == "pin_wrong"
    assert capfd.readouterr().out.count("security.pin_reset") == 0

    response = await head.post(f"{USERS}/{mine}/pin-reset", json={"pin": PIN})
    assert response.status_code == 200
    assert response.json()["pin_locked"] is False
    out = capfd.readouterr().out
    (logged,) = events(out, "security.pin_reset")
    assert logged["user_id"] == str(mine)
    assert logged["by_user_id"] == str(head_id)
    assert PIN not in out
    assert WRONG not in out
    async with app.state.engine.begin() as conn:
        row = (
            await conn.execute(
                select(tables.app_user.c.pin_hash, tables.app_user.c.pin_locked_at).where(
                    tables.app_user.c.id == other
                )
            )
        ).one()
    assert row.pin_hash is not None
    assert row.pin_locked_at is not None


@pytest.mark.asyncio
async def test_personas_cannot_list_invite_revoke_or_reset(app: FastAPI) -> None:
    target = await add_google_user(
        app, "ph.nurse@example.com", Role.STAFF_NURSE, "ph-demo", pin=PIN, sub="s1"
    )
    for persona in DEMO_PERSONAS:
        async with client_for(app) as client:
            await sign_in(client, persona.id)
            for method, path, body in requests_of(target):
                if body is not None:
                    body = body | {"pin": DEMO_PIN}
                response = await client.request(method, path, json=body)
                assert response.status_code == 403, (persona.display_name, method, path)
    # Nothing happened to the real nurse.
    assert (await app.state.users.get_user(target)).status.value == "active"


@pytest.mark.asyncio
async def test_test_session_route_is_404_outside_test(
    database_url: str, clock: MutableClock
) -> None:
    for env in ("dev", "demo", "prod"):
        async with running_app(database_url, clock, env) as app, client_for(app) as client:
            for path in ("/api/v1/test/session", "/api/v1/test/teardown"):
                response = await client.post(
                    path, json={"role": "admin", "facility_key": None, "pin": None}
                )
                assert response.status_code == 404, (env, path)


@pytest.mark.asyncio
async def test_test_session_signs_in_a_throwaway_google_user(
    app: FastAPI, client: httpx.AsyncClient, capfd: pytest.CaptureFixture[str]
) -> None:
    capfd.readouterr()
    plain = await client.post(
        "/api/v1/test/session", json={"role": "staff_nurse", "facility_key": "ph-demo", "pin": None}
    )
    assert plain.status_code == 201
    assert plain.json()["kind"] == "google"
    assert plain.json()["gate"] == "set_pin"
    assert "sl_session" in client.cookies

    async with client_for(app) as second:
        with_pin = await second.post(
            "/api/v1/test/session",
            json={"role": "head_nurse", "facility_key": "us-demo", "pin": PIN},
        )
        assert with_pin.status_code == 201
        assert with_pin.json()["gate"] == "enter_pin"
        assert with_pin.json()["facility_key"] == "us-demo"
    assert PIN not in capfd.readouterr().out

    async with app.state.engine.begin() as conn:
        rows = (
            await conn.execute(
                select(tables.app_user.c.email, tables.app_user.c.google_sub).where(
                    tables.app_user.c.email.like("e2e-%")
                )
            )
        ).all()
    assert len(rows) == 2
    for email, sub in rows:
        assert email.startswith("e2e-")
        assert email.endswith("@example.com")
        assert sub == email.removesuffix("@example.com")


@pytest.mark.asyncio
async def test_test_teardown_revokes_without_deleting(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    made = await client.post(
        "/api/v1/test/session", json={"role": "staff_nurse", "facility_key": "ph-demo", "pin": None}
    )
    user_id = made.json()["user_id"]
    keep = await add_google_user(app, "keep.me@example.com", Role.STAFF_NURSE, "ph-demo", sub="k")

    assert (await client.post("/api/v1/test/teardown")).status_code == 204
    assert (await client.get("/api/v1/session")).status_code == 401
    assert (await app.state.users.get_user(UUID(user_id))).status.value == "revoked"
    assert (await app.state.users.get_user(keep)).status.value == "active"
    assert (await client.post("/api/v1/test/teardown")).status_code == 204


@pytest.mark.asyncio
async def test_the_seed_admin_persona_is_not_a_real_admin(client: httpx.AsyncClient) -> None:
    await sign_in(client, ADMIN)
    assert (await client.get(USERS)).status_code == 403
