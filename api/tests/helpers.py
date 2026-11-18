"""Helpers the API tests share: a clock the test can move, signing in, an invited nurse, a
provider a test can fail on demand, and the privacy check."""

import asyncio
import hashlib
import secrets
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
from argon2 import PasswordHasher
from fastapi import FastAPI
from nursing_api.app import create_app
from nursing_api.auth.oidc import GoogleOidc
from nursing_api.routes import SESSION_COOKIE
from nursing_api.settings import Settings
from nursing_core.demo import DemoCase, load_demo_cases
from nursing_core.domain.model_output import DraftRequest, ProviderResult
from nursing_core.domain.patient import PatientRecord
from nursing_core.domain.shifts import default_shift
from nursing_core.domain.users import Role
from nursing_core.ports import LlmProvider
from nursing_core.providers.fake import FakeProvider
from nursing_core.storage import tables
from nursing_core.storage.rows import shift_columns
from sqlalchemy import insert, select, update

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
    database_url: str,
    clock: MutableClock,
    app_env: str = "test",
    *,
    provider_for: Callable[[PatientRecord], LlmProvider] | None = None,
    google: GoogleOidc | None = None,
    **settings_values: object,
) -> AsyncGenerator[FastAPI]:
    """The app with its lifespan running, on the given database and clock.

    `provider_for` replaces the AI provider and `google` the Google client (tests never reach the
    network); extra keyword arguments are more settings, such as `ai_mode="live"`.
    """
    settings = Settings.model_validate(
        {"database_url": database_url, "app_env": app_env, **settings_values}
    )
    app = create_app(settings, clock=clock, provider_for=provider_for, google=google)
    async with app.router.lifespan_context(app):
        yield app


class AppClient(httpx.AsyncClient):
    """A client on one app, which `sign_in` needs to write a session into the app's database."""

    def __init__(self, app: FastAPI) -> None:
        # Answers 500 for an unexpected error, as a server would, instead of raising.
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        super().__init__(transport=transport, base_url="http://test")
        self.app = app


def client_for(app: FastAPI) -> AppClient:
    return AppClient(app)


async def sign_in(client: httpx.AsyncClient, persona_id: UUID) -> httpx.Response:
    """Sign in as a demo persona whose PIN is already proved: the session is open, as every test
    of a data route needs once the server enforces the PIN gate. The client keeps the cookie and
    sends the session's CSRF token from then on. Answers what GET /api/v1/session answers.

    It writes the session row itself, through the table (frozen by the contract), so a change to
    the session repository's methods never breaks the tests that only need to be signed in.
    Tests of signing in itself call POST /api/v1/session.
    """
    assert isinstance(client, AppClient), "sign in with a client from client_for(app)"
    state = client.app.state
    now: datetime = state.clock.now()
    user = await state.users.get_user(persona_id)
    shift, hours = None, 12  # the admin's session: no shift, 12 hours
    if user.facility_key is not None:
        profile = (await state.facilities.get_facility(user.facility_key)).profile
        shift, hours = default_shift(now, profile), profile.session_max_hours
    token, csrf_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    async with state.engine.begin() as conn:
        await conn.execute(
            insert(tables.session).values(
                token_hash=hashlib.sha256(token.encode()).hexdigest(),
                user_id=user.id,
                created_at=now,
                expires_at=now + timedelta(hours=hours),
                csrf_token=csrf_token,
                pin_verified_at=now,
                last_active_at=now,
                **shift_columns(shift),
            )
        )
    client.cookies.set(SESSION_COOKIE.model.name, token)
    client.headers["X-CSRF-Token"] = csrf_token
    response = await client.get("/api/v1/session")
    assert response.status_code == 200, response.text
    return response


async def keep_open(client: httpx.AsyncClient) -> None:
    """Marks the signed-in session active now, for a test that moves the clock on purpose: past
    the idle lock it would answer 423. It never moves the session's expiry."""
    assert isinstance(client, AppClient), "use a client from client_for(app)"
    state = client.app.state
    token = client.cookies[SESSION_COOKIE.model.name]
    async with state.engine.begin() as conn:
        await conn.execute(
            update(tables.session)
            .where(tables.session.c.token_hash == hashlib.sha256(token.encode()).hexdigest())
            .values(last_active_at=state.clock.now())
        )


async def post_note(
    client: httpx.AsyncClient, patient_id: UUID, text: str, key: str = "key-1"
) -> httpx.Response:
    """Save a rough note as the signed-in nurse."""
    return await client.post(
        f"/api/v1/patients/{patient_id}/rough-notes",
        json={"text": text},
        headers={"Idempotency-Key": key},
    )


async def drain(app: FastAPI) -> None:
    """Wait for every draft job the app has started."""
    await app.state.queue.drain()


def draft_path(rough_note_id: object) -> str:
    """The "Try drafting again" route of a rough note."""
    return f"/api/v1/rough-notes/{rough_note_id}/draft-jobs"


async def add_invited_nurse(app: FastAPI, facility_key: str) -> UUID:
    """A non-persona staff nurse (an invited one) at the facility, with a PIN already set."""
    user_id = uuid4()
    async with app.state.engine.begin() as conn:
        facility_id = (
            await conn.execute(
                select(tables.facility.c.id).where(tables.facility.c.key == facility_key)
            )
        ).scalar_one()
        await conn.execute(
            insert(tables.app_user).values(
                id=user_id,
                display_name="Invited Nurse",
                initials="IN",
                role=Role.STAFF_NURSE.value,
                facility_id=facility_id,
                email=f"e2e-{uuid4()}@example.com",
                persona=False,
                pin_hash=PasswordHasher().hash(uuid4().hex),
            )
        )
    return user_id


class SwitchableProvider:
    """Raises `error` until a test clears it, then drafts the PH demo case; can wait on a gate."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.gate: asyncio.Event | None = None
        self.calls = 0
        case = next(case for case in load_demo_cases() if case.facility_key == "ph-demo")
        self._inner = FakeProvider(case.model_output)

    async def draft_fdar(self, request: DraftRequest) -> ProviderResult:
        self.calls += 1
        if self.gate is not None:
            await self.gate.wait()
        if self.error is not None:
            raise self.error
        return await self._inner.draft_fdar(request)

    def for_patient(self, _patient: PatientRecord) -> LlmProvider:
        return self


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


def leaked(text: str, cases: list[DemoCase]) -> list[str]:
    """The forbidden strings of every case that appear (case-insensitively) in `text`."""
    lowered = text.lower()
    return [word for case in cases for word in forbidden_words(case) if word in lowered]
