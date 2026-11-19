"""Signing in with Google: the start and callback routes, run against the real verifier and a
local fake Google (no test reaches the network)."""

import base64
import hashlib
import json
import time
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock
from urllib.parse import urlsplit
from uuid import UUID

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from joserfc.errors import JoseError
from nursing_api.auth.google import AuthlibGoogleOidc
from nursing_api.logging import ALLOWED_KEYS
from nursing_core.domain.errors import DatabaseWaking
from nursing_core.domain.users import Role
from nursing_core.storage import tables
from sqlalchemy import func, select, update

from .fake_google import (
    CALLBACK,
    CLIENT_ID,
    CLIENT_SECRET,
    DISCOVERY_URL,
    JWKS_URL,
    SITE_URL,
    START,
    FakeGoogle,
    add_google_user,
    google_sign_in,
    query_of,
)
from .helpers import MutableClock, client_for, running_app

SESSION = "/api/v1/session"
UNLOCK = f"{SESSION}/unlock"
PATIENTS = "/api/v1/patients"
BOOTSTRAP = "gale.admin@example.com"
PIN = "246813"
WRONG = "975310"
REFUSED = f"{SITE_URL}/sign-in?error="


@pytest.fixture
def fake() -> FakeGoogle:
    return FakeGoogle()


@pytest_asyncio.fixture
async def gapp(database_url: str, clock: MutableClock, fake: FakeGoogle) -> AsyncIterator[FastAPI]:
    google = AuthlibGoogleOidc(CLIENT_ID, CLIENT_SECRET, transport=fake.transport)
    async with running_app(
        database_url,
        clock,
        google=google,
        site_url=SITE_URL,
        google_client_id=CLIENT_ID,
        google_client_secret=CLIENT_SECRET,
        bootstrap_admin_email=BOOTSTRAP,
    ) as app:
        yield app


@pytest_asyncio.fixture
async def gclient(gapp: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with client_for(gapp) as http:
        yield http


def events(out: str, name: str = "security.sign_in_refused") -> list[dict[str, Any]]:
    lines = [json.loads(line) for line in out.splitlines() if line.startswith("{")]
    return [line for line in lines if line.get("event") == name]


def cookie_lines(response: httpx.Response, name: str) -> list[str]:
    return [c for c in response.headers.get_list("set-cookie") if c.startswith(f"{name}=")]


def assert_refused(response: httpx.Response, error: str) -> None:
    """A redirect to the sign-in page with that reason, no session, the attempt's cookie gone."""
    assert response.status_code == 302
    assert response.headers["location"] == f"{REFUSED}{error}"
    assert cookie_lines(response, "sl_session") == []
    assert_attempt_cleared(response)


def assert_attempt_cleared(response: httpx.Response) -> None:
    (line,) = cookie_lines(response, "sl_oauth")
    assert "max-age=0" in line.lower()


async def count(app: FastAPI, table: Any) -> int:
    async with app.state.engine.connect() as conn:
        return int(await conn.scalar(select(func.count()).select_from(table)) or 0)


async def user_by_email(app: FastAPI, email: str) -> Any:
    async with app.state.engine.connect() as conn:
        return (
            await conn.execute(select(tables.app_user).where(tables.app_user.c.email == email))
        ).one()


@pytest.mark.asyncio
async def test_start_redirects_with_pkce_state_nonce_and_select_account(
    gclient: httpx.AsyncClient,
) -> None:
    response = await gclient.get(START)

    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    query = query_of(location)
    assert query["response_type"] == "code"
    assert query["client_id"] == CLIENT_ID
    assert query["redirect_uri"] == f"{SITE_URL}{CALLBACK}"
    assert query["scope"] == "openid email profile"
    assert query["prompt"] == "select_account"
    assert query["code_challenge_method"] == "S256"
    assert len(query["code_challenge"]) == 43  # base64url of a SHA-256, unpadded
    assert len(query["state"]) >= 32
    assert len(query["nonce"]) >= 32
    (cookie,) = cookie_lines(response, "sl_oauth")
    lowered = cookie.lower()
    assert "httponly" in lowered
    assert "samesite=lax" in lowered
    assert "max-age=600" in lowered
    assert f"path={CALLBACK}" in lowered
    assert "secure" not in lowered  # the test environment is plain http
    # The attempt's secrets are not readable in the cookie, and nothing is in the page.
    for secret in (query["state"], query["nonce"]):
        assert secret not in cookie
    # Each start is its own attempt.
    again = query_of((await gclient.get(START)).headers["location"])
    assert (again["state"], again["nonce"]) != (query["state"], query["nonce"])


@pytest.mark.asyncio
@pytest.mark.parametrize(("app_env", "secure"), [("demo", True), ("prod", True), ("dev", False)])
async def test_the_attempt_cookie_is_secure_in_demo_and_prod(
    database_url: str, clock: MutableClock, fake: FakeGoogle, app_env: str, secure: bool
) -> None:
    google = AuthlibGoogleOidc(CLIENT_ID, CLIENT_SECRET, transport=fake.transport)
    async with (
        running_app(
            database_url,
            clock,
            app_env,
            google=google,
            site_url=SITE_URL,
            google_client_id=CLIENT_ID,
            google_client_secret=CLIENT_SECRET,
        ) as app,
        client_for(app) as client,
    ):
        response = await client.get(START)
    (cookie,) = cookie_lines(response, "sl_oauth")
    assert ("secure" in cookie.lower()) is secure


@pytest.mark.asyncio
@pytest.mark.parametrize(("app_env", "secure"), [("demo", True), ("prod", True), ("dev", False)])
async def test_the_session_cookie_is_secure_in_demo_and_prod(
    database_url: str, clock: MutableClock, fake: FakeGoogle, app_env: str, secure: bool
) -> None:
    google = AuthlibGoogleOidc(CLIENT_ID, CLIENT_SECRET, transport=fake.transport)
    async with (
        running_app(
            database_url,
            clock,
            app_env,
            google=google,
            site_url=SITE_URL,
            google_client_id=CLIENT_ID,
            google_client_secret=CLIENT_SECRET,
        ) as app,
        client_for(app) as client,
    ):
        client.base_url = httpx.URL(
            "https://test"
        )  # a Secure attempt cookie comes back only on https
        await add_google_user(app, "sam.nurse@example.com", Role.STAFF_NURSE, "us-demo")
        response = await google_sign_in(client, fake, email="sam.nurse@example.com", sub="sub-sam")
    (cookie,) = cookie_lines(response, "sl_session")
    assert ("secure" in cookie.lower().split("; ")) is secure


@pytest.mark.asyncio
async def test_start_is_404_when_google_is_off(client: httpx.AsyncClient) -> None:
    response = await client.get(START)
    assert response.status_code == 404
    assert cookie_lines(response, "sl_oauth") == []
    # The callback is just as closed, and sets no session.
    answered = await client.get(CALLBACK, params={"code": "x", "state": "y"})
    assert answered.status_code == 404
    assert cookie_lines(answered, "sl_session") == []


@pytest.mark.asyncio
async def test_callback_with_another_browsers_state_is_refused(
    gapp: FastAPI, gclient: httpx.AsyncClient, fake: FakeGoogle, capfd: pytest.CaptureFixture[str]
) -> None:
    await add_google_user(gapp, "sam.nurse@example.com", Role.STAFF_NURSE, "us-demo")
    started = await gclient.get(START)
    query = query_of(started.headers["location"])
    code = fake.grant(
        nonce=query["nonce"],
        code_challenge=query["code_challenge"],
        sub="sub-sam",
        email="sam.nurse@example.com",
    )
    capfd.readouterr()

    # A second browser has no attempt of its own: the first one's state opens nothing for it.
    async with client_for(gapp) as other:
        refused = await other.get(CALLBACK, params={"code": code, "state": query["state"]})
    assert_refused(refused, "expired")
    # The same browser with a state that is not its own is refused too.
    wrong = await gclient.get(CALLBACK, params={"code": code, "state": "not-its-state"})
    assert_refused(wrong, "expired")
    missing = await gclient.get(CALLBACK, params={"code": code})
    assert_refused(missing, "expired")

    await gclient.get(START)  # each refusal ended the attempt: begin another
    odd = await gclient.get(CALLBACK, params={"code": code, "state": "é"})
    assert_refused(odd, "expired")  # a state that isn't ASCII is a mismatch, never a crash

    logged = events(capfd.readouterr().out)
    assert [e["reason"] for e in logged] == ["state_mismatch"] * 4
    assert all(set(e) <= ALLOWED_KEYS for e in logged)
    # The code was never exchanged.
    assert [r for r in fake.requests if r[1].endswith("/token")] == []


@pytest.mark.asyncio
async def test_an_attempt_older_than_ten_minutes_or_garbled_is_expired(
    gclient: httpx.AsyncClient, clock: MutableClock, fake: FakeGoogle
) -> None:
    started = await gclient.get(START)
    query = query_of(started.headers["location"])
    clock.advance(timedelta(minutes=10, seconds=1))
    old = await gclient.get(CALLBACK, params={"code": "c", "state": query["state"]})
    assert_refused(old, "expired")

    gclient.cookies.set("sl_oauth", "garbled", path=CALLBACK)
    garbled = await gclient.get(CALLBACK, params={"code": "c", "state": query["state"]})
    assert_refused(garbled, "expired")

    # A cookie another site could plant is not ours: it is signed with a key only we hold.
    gclient.cookies.set("sl_oauth", "-".join(["unsigned", "attempt"]) + ".AAAA", path=CALLBACK)
    forged = await gclient.get(CALLBACK, params={"code": "c", "state": "s"})
    assert_refused(forged, "expired")


@pytest.mark.asyncio
async def test_google_saying_no_is_cancelled_and_logs_nothing(
    gclient: httpx.AsyncClient, capfd: pytest.CaptureFixture[str]
) -> None:
    await gclient.get(START)
    capfd.readouterr()

    response = await gclient.get(CALLBACK, params={"error": "access_denied", "state": "s"})

    assert_refused(response, "cancelled")
    assert events(capfd.readouterr().out) == []


@pytest.mark.asyncio
async def test_callback_on_a_waking_database_sends_her_back_to_sign_in(
    gapp: FastAPI,
    gclient: httpx.AsyncClient,
    fake: FakeGoogle,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        gapp.state.users, "get_user_by_email", AsyncMock(side_effect=DatabaseWaking("waking"))
    )
    capfd.readouterr()

    response = await google_sign_in(gclient, fake, email="pat.nurse@example.com")

    assert_refused(response, "expired")  # a redirect, never the raw 503 page
    logged = events(capfd.readouterr().out)
    assert [e["reason"] for e in logged] == ["database_waking"]
    assert "pat.nurse" not in json.dumps(logged)


@pytest.mark.asyncio
async def test_uninvited_email_gets_no_access_and_no_session(
    gapp: FastAPI,
    gclient: httpx.AsyncClient,
    fake: FakeGoogle,
    capfd: pytest.CaptureFixture[str],
) -> None:
    before = await count(gapp, tables.app_user)
    capfd.readouterr()

    response = await google_sign_in(gclient, fake, email="stranger@example.com")

    assert_refused(response, "no_access")
    assert await count(gapp, tables.app_user) == before  # nobody is made from a sign-in
    assert (await gclient.get(SESSION)).status_code == 401
    logged = events(capfd.readouterr().out)
    assert [e["reason"] for e in logged] == ["no_access"]
    assert "stranger" not in json.dumps(logged)


@pytest.mark.asyncio
async def test_revoked_user_gets_no_access_and_no_session(
    gapp: FastAPI, gclient: httpx.AsyncClient, fake: FakeGoogle, clock: MutableClock
) -> None:
    user_id = await add_google_user(
        gapp, "gone.nurse@example.com", Role.STAFF_NURSE, "us-demo", sub="sub-gone"
    )
    async with gapp.state.engine.begin() as conn:
        await conn.execute(
            update(tables.app_user)
            .where(tables.app_user.c.id == user_id)
            .values(revoked_at=clock.now())
        )

    response = await google_sign_in(gclient, fake, email="gone.nurse@example.com", sub="sub-gone")

    assert_refused(response, "no_access")
    assert await count(gapp, tables.session) == 0


@pytest.mark.asyncio
async def test_first_sign_in_asks_for_a_new_pin(
    gapp: FastAPI, gclient: httpx.AsyncClient, fake: FakeGoogle, clock: MutableClock
) -> None:
    user_id = await add_google_user(gapp, "sam.nurse@example.com", Role.STAFF_NURSE, "us-demo")
    assert (await gapp.state.users.get_user(user_id)).status == "invited"

    response = await google_sign_in(
        gclient, fake, email="Sam.Nurse@Example.com", sub="sub-sam", name="Sam Q. Rivers"
    )

    assert response.status_code == 302
    assert response.headers["location"] == f"{SITE_URL}/"
    assert_attempt_cleared(response)
    (session_cookie,) = cookie_lines(response, "sl_session")
    lowered = session_cookie.lower()
    assert "httponly" in lowered
    assert "samesite=lax" in lowered
    assert "path=/;" in lowered
    assert f"max-age={14 * 3600}" in lowered  # the US facility's 14 hours
    session = (await gclient.get(SESSION)).json()
    assert (session["kind"], session["gate"]) == ("google", "set_pin")
    assert (session["display_name"], session["initials"]) == ("Sam Q. Rivers", "SR")
    assert (session["role"], session["facility_key"], session["user_id"]) == (
        "staff_nurse",
        "us-demo",
        str(user_id),
    )
    assert session["shift"] is not None
    stored = await gapp.state.users.get_user(user_id)
    assert stored.status == "active"
    assert not stored.has_pin
    # Until she sets a PIN no patient data opens, and the PIN is the next step.
    assert (await gclient.get(PATIENTS)).json()["code"] == "set_pin"
    # The second sign-in, from the same account, finds her active and asks for the PIN she set.
    async with client_for(gapp) as again:
        second = await google_sign_in(again, fake, email="sam.nurse@example.com", sub="sub-sam")
    assert second.headers["location"] == f"{SITE_URL}/"
    # Google's keys and discovery document were fetched once, however many sign-ins.
    assert [r[1] for r in fake.requests].count(DISCOVERY_URL) == 1
    assert [r[1] for r in fake.requests].count(JWKS_URL) == 1


@pytest.mark.asyncio
async def test_bootstrap_admin_created_on_first_sign_in(
    gapp: FastAPI, gclient: httpx.AsyncClient, fake: FakeGoogle
) -> None:
    assert await _admins(gapp) == 0

    response = await google_sign_in(
        gclient, fake, email=BOOTSTRAP.upper(), sub="sub-gale", name="Gale Admin"
    )

    assert response.headers["location"] == f"{SITE_URL}/"
    (session_cookie,) = cookie_lines(response, "sl_session")
    assert f"max-age={12 * 3600}" in session_cookie.lower()
    session = (await gclient.get(SESSION)).json()
    assert (session["role"], session["facility_key"], session["shift"]) == ("admin", None, None)
    assert (session["kind"], session["gate"]) == ("google", "set_pin")
    assert (session["display_name"], session["initials"]) == ("Gale Admin", "GA")
    # Once an active Google admin exists, the configured address is not made one again.
    assert await _admins(gapp) == 1


async def _admins(app: FastAPI) -> int:
    async with app.state.engine.connect() as conn:
        return int(
            await conn.scalar(
                select(func.count())
                .select_from(tables.app_user)
                .where(tables.app_user.c.role == "admin", tables.app_user.c.persona.is_(False))
            )
            or 0
        )


@pytest.mark.asyncio
async def test_a_missing_name_falls_back_to_the_part_before_the_at_sign(
    gapp: FastAPI, gclient: httpx.AsyncClient, fake: FakeGoogle
) -> None:
    await add_google_user(gapp, "pat.lee@example.com", Role.HEAD_NURSE, "ph-demo")

    response = await google_sign_in(gclient, fake, email="pat.lee@example.com", name=None)

    assert response.headers["location"] == f"{SITE_URL}/"
    session = (await gclient.get(SESSION)).json()
    assert (session["display_name"], session["initials"]) == ("pat.lee", "P")


@pytest.mark.asyncio
async def test_second_google_account_for_the_same_email_is_refused(
    gapp: FastAPI,
    gclient: httpx.AsyncClient,
    fake: FakeGoogle,
    capfd: pytest.CaptureFixture[str],
) -> None:
    user_id = await add_google_user(
        gapp, "sam.nurse@example.com", Role.STAFF_NURSE, "us-demo", sub="sub-sam"
    )
    capfd.readouterr()

    response = await google_sign_in(gclient, fake, email="sam.nurse@example.com", sub="sub-other")

    assert_refused(response, "no_access")
    assert (await user_by_email(gapp, "sam.nurse@example.com")).google_sub == "sub-sam"
    assert await count(gapp, tables.session) == 0
    (event,) = events(capfd.readouterr().out)
    assert (event["reason"], event["user_id"]) == ("identity_mismatch", str(user_id))


@pytest.mark.asyncio
async def test_unverified_email_is_refused(
    gapp: FastAPI,
    gclient: httpx.AsyncClient,
    fake: FakeGoogle,
    capfd: pytest.CaptureFixture[str],
) -> None:
    await add_google_user(gapp, "sam.nurse@example.com", Role.STAFF_NURSE, "us-demo")
    capfd.readouterr()

    response = await google_sign_in(
        gclient, fake, email="sam.nurse@example.com", email_verified=False
    )

    assert_refused(response, "no_access")
    assert (await user_by_email(gapp, "sam.nurse@example.com")).google_sub is None
    assert [e["reason"] for e in events(capfd.readouterr().out)] == ["email_unverified"]


@pytest.mark.asyncio
async def test_id_token_for_another_client_is_refused(
    gapp: FastAPI,
    gclient: httpx.AsyncClient,
    fake: FakeGoogle,
    capfd: pytest.CaptureFixture[str],
) -> None:
    await add_google_user(gapp, "sam.nurse@example.com", Role.STAFF_NURSE, "us-demo")
    capfd.readouterr()

    response = await google_sign_in(
        gclient, fake, email="sam.nurse@example.com", aud="someone-elses-client.example.com"
    )

    assert_refused(response, "expired")
    assert (await user_by_email(gapp, "sam.nurse@example.com")).google_sub is None
    assert [e["reason"] for e in events(capfd.readouterr().out)] == ["token_invalid"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        {"iss": "https://evil.example.com"},
        {"expires_in": -60},
        {"nonce": "another-nonce"},
        {"extra": {"email": None}},
        {"sign_with": "foreign"},
    ],
    ids=["issuer", "expired", "nonce", "no_email", "signature"],
)
async def test_every_other_id_token_failure_is_refused(
    gapp: FastAPI, gclient: httpx.AsyncClient, fake: FakeGoogle, bad: dict[str, Any]
) -> None:
    await add_google_user(gapp, "sam.nurse@example.com", Role.STAFF_NURSE, "us-demo")
    grant: dict[str, Any] = {
        k: (fake.foreign_key() if v == "foreign" else v) for k, v in bad.items()
    }

    response = await google_sign_in(gclient, fake, email="sam.nurse@example.com", **grant)

    assert_refused(response, "expired")
    assert await count(gapp, tables.session) == 0


@pytest.mark.asyncio
async def test_a_rejected_code_exchange_is_refused(
    gclient: httpx.AsyncClient,
) -> None:
    started = await gclient.get(START)
    state = query_of(started.headers["location"])["state"]

    response = await gclient.get(CALLBACK, params={"code": "never-issued", "state": state})

    assert_refused(response, "expired")


@pytest.mark.asyncio
async def test_callback_url_comes_from_site_url_not_the_host_header(
    gapp: FastAPI, gclient: httpx.AsyncClient, fake: FakeGoogle
) -> None:
    evil = {"host": "evil.example.org"}
    started = await gclient.get(START, headers=evil)
    assert query_of(started.headers["location"])["redirect_uri"] == f"{SITE_URL}{CALLBACK}"
    assert urlsplit(started.headers["location"]).netloc == "accounts.google.com"
    await add_google_user(gapp, "sam.nurse@example.com", Role.STAFF_NURSE, "us-demo")

    query = query_of(started.headers["location"])
    code = fake.grant(
        nonce=query["nonce"],
        code_challenge=query["code_challenge"],
        sub="sub-sam",
        email="sam.nurse@example.com",
    )
    signed_in = await gclient.get(
        CALLBACK, params={"code": code, "state": query["state"]}, headers=evil
    )
    assert signed_in.headers["location"] == f"{SITE_URL}/"
    cancelled = await gclient.get(CALLBACK, params={"error": "access_denied"}, headers=evil)
    assert cancelled.headers["location"] == f"{REFUSED}cancelled"


@pytest.mark.asyncio
async def test_leftover_google_session_cannot_see_patients_without_the_pin(
    gapp: FastAPI,
    gclient: httpx.AsyncClient,
    fake: FakeGoogle,
    capfd: pytest.CaptureFixture[str],
) -> None:
    sam = await add_google_user(
        gapp, "sam.nurse@example.com", Role.STAFF_NURSE, "us-demo", sub="sub-sam", pin=PIN
    )
    pat = await add_google_user(
        gapp, "pat.lee@example.com", Role.STAFF_NURSE, "us-demo", sub="sub-pat", pin=PIN
    )

    response = await google_sign_in(gclient, fake, email="sam.nurse@example.com", sub="sub-sam")
    assert response.headers["location"] == f"{SITE_URL}/"
    session = (await gclient.get(SESSION)).json()
    assert (session["kind"], session["gate"]) == ("google", "enter_pin")
    gclient.headers["X-CSRF-Token"] = session["csrf_token"]

    # She walked away after signing in: the browser still holds the cookie, and sees nothing.
    locked = await gclient.get(PATIENTS)
    assert (locked.status_code, locked.json()["code"]) == (423, "enter_pin")
    capfd.readouterr()

    # Anyone at that screen gets five tries, and the fifth locks her PIN, nobody else's.
    answers = [await gclient.post(UNLOCK, json={"pin": WRONG}) for _ in range(5)]
    assert [a.status_code for a in answers] == [403, 403, 403, 403, 423]
    assert answers[4].json()["code"] == "pin_locked"
    assert (await gclient.get(PATIENTS)).json()["code"] == "pin_locked"
    assert (await gclient.post(UNLOCK, json={"pin": PIN})).status_code == 423
    assert (await gapp.state.users.get_user(sam)).pin_locked
    assert not (await gapp.state.users.get_user(pat)).pin_locked
    assert not any(u.pin_locked for u in await _personas(gapp))
    out = capfd.readouterr().out
    assert [e["user_id"] for e in events(out, "security.pin_locked")] == [str(sam)]
    for secret in (PIN, WRONG, session["csrf_token"], gclient.cookies["sl_session"]):
        assert secret not in out


async def _personas(app: FastAPI) -> list[Any]:
    return [
        await app.state.users.get_user(UUID(f"00000000-0000-4000-8000-00000000{n}"))
        for n in ("0101", "0102", "0201", "0202", "0901")
    ]


@pytest.mark.asyncio
async def test_sign_in_logs_carry_no_email_code_state_nonce_or_token(
    gapp: FastAPI,
    gclient: httpx.AsyncClient,
    fake: FakeGoogle,
    capfd: pytest.CaptureFixture[str],
) -> None:
    await add_google_user(gapp, "sam.nurse@example.com", Role.STAFF_NURSE, "us-demo")
    started = await gclient.get(START)
    query = query_of(started.headers["location"])
    code = fake.grant(
        nonce="wrong-nonce",
        code_challenge=query["code_challenge"],
        sub="sub-sam",
        email="sam.nurse@example.com",
    )
    capfd.readouterr()

    await gclient.get(CALLBACK, params={"code": code, "state": query["state"]})
    await google_sign_in(gclient, fake, email="stranger@example.com", sub="sub-x")

    out = capfd.readouterr().out
    for secret in ("sam.nurse", "stranger", code, query["state"], query["nonce"], "sub-sam"):
        assert secret not in out
    assert [e["reason"] for e in events(out)] == ["token_invalid", "no_access"]


async def verified(
    fake: FakeGoogle, nonce: str = "n", *, expected_nonce: str = "n", **grant: Any
) -> Any:
    """Runs the real exchange and verifier against the fake, with no app or database."""
    google = AuthlibGoogleOidc(CLIENT_ID, CLIENT_SECRET, transport=fake.transport)
    verifier = "v" * 64
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    code = fake.grant(
        nonce=nonce,
        code_challenge=challenge.rstrip(b"=").decode(),
        sub="sub-1",
        email="a@example.com",
        **grant,
    )
    token = await google.exchange(code=code, code_verifier=verifier, redirect_uri="http://x/cb")
    return await google.verify_id_token(token, nonce=expected_nonce)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("grant", "expected_nonce", "error"),
    [
        ({"iss": "https://evil.example.com"}, "n", "InvalidClaimError"),
        ({"aud": "someone-else.example.com"}, "n", "InvalidClaimError"),
        ({"expires_in": -600}, "n", "ExpiredTokenError"),
        ({}, "another-nonce", "InvalidClaimError"),
        ({"extra": {"email": None}}, "n", "MissingClaimError"),
        ({"sign_with": "foreign"}, "n", "InvalidKeyIdError"),
    ],
    ids=["issuer", "audience", "expired", "nonce", "no_email", "signature"],
)
async def test_the_verifier_names_what_was_wrong_with_the_token(
    fake: FakeGoogle, grant: dict[str, Any], expected_nonce: str, error: str
) -> None:
    grant = {k: (fake.foreign_key() if v == "foreign" else v) for k, v in grant.items()}
    with pytest.raises(JoseError) as caught:
        await verified(fake, expected_nonce=expected_nonce, **grant)
    assert type(caught.value).__name__ == error


@pytest.mark.asyncio
async def test_a_minute_of_clock_drift_is_tolerated_but_not_more(fake: FakeGoogle) -> None:
    now = int(time.time())
    identity = await verified(fake, extra={"iat": now + 30})
    assert identity.email == "a@example.com"
    with pytest.raises(JoseError) as caught:
        await verified(fake, extra={"iat": now + 90})
    assert type(caught.value).__name__ == "InvalidClaimError"


@pytest.mark.asyncio
async def test_a_refused_token_logs_the_error_class(
    gclient: httpx.AsyncClient, fake: FakeGoogle, capfd: pytest.CaptureFixture[str]
) -> None:
    capfd.readouterr()
    await google_sign_in(gclient, fake, email="a@example.com", aud="other.example.com")
    logged = events(capfd.readouterr().out)
    assert [(e["reason"], e["error_class"]) for e in logged] == [
        ("token_invalid", "InvalidClaimError")
    ]


@pytest.mark.asyncio
async def test_a_successful_sign_in_logs_no_session_csrf_email_sub_code_or_state(
    gapp: FastAPI,
    gclient: httpx.AsyncClient,
    fake: FakeGoogle,
    capfd: pytest.CaptureFixture[str],
) -> None:
    await add_google_user(gapp, "sam.nurse@example.com", Role.STAFF_NURSE, "us-demo")
    started = await gclient.get(START)
    query = query_of(started.headers["location"])
    code = fake.grant(
        nonce=query["nonce"],
        code_challenge=query["code_challenge"],
        sub="sub-sam-secret",
        email="sam.nurse@example.com",
    )
    capfd.readouterr()

    done = await gclient.get(CALLBACK, params={"code": code, "state": query["state"]})
    assert done.headers["location"] == f"{SITE_URL}/"
    session = (await gclient.get(SESSION)).json()

    out = capfd.readouterr().out
    secrets_ = [
        gclient.cookies["sl_session"],
        session["csrf_token"],
        "sam.nurse",
        "sub-sam-secret",
        code,
        query["state"],
        query["nonce"],
    ]
    for secret in secrets_:
        assert secret not in out
    assert events(out, "security.sign_in_refused") == []
