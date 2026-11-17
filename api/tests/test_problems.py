"""Domain errors answer as RFC 9457 problem documents, whatever route raised them."""

from collections.abc import Callable

import httpx
import pytest
from fastapi import FastAPI
from nursing_api.app import create_app
from nursing_api.problems import (
    CsrfFailed,
    DailyDraftLimit,
    NotSignedIn,
    PinAlreadySet,
    PinWrong,
    PreconditionRequired,
    SessionGated,
)
from nursing_api.settings import Settings
from nursing_core.domain.errors import (
    AlreadyDrafted,
    DatabaseWaking,
    EmailTaken,
    Forbidden,
    IdempotencyConflict,
    NoteLocked,
    NotFound,
    NotRetryable,
    ReviewIncomplete,
    StaleVersion,
)
from nursing_core.domain.users import SessionGate

CASES: list[tuple[Callable[[], Exception], int, str]] = [
    (lambda: NotSignedIn(), 401, "not_signed_in"),
    (lambda: Forbidden("zebracanary"), 403, "forbidden"),
    (lambda: NotFound("zebracanary"), 404, "not_found"),
    (lambda: NoteLocked("zebracanary"), 409, "note_locked"),
    (lambda: ReviewIncomplete(["e1-D2", "e1-A1"]), 409, "review_incomplete"),
    (lambda: StaleVersion("zebracanary"), 412, "stale_version"),
    (lambda: IdempotencyConflict("zebracanary"), 422, "idempotency_key_reused"),
    (lambda: PreconditionRequired("If-Match"), 428, "precondition_required"),
    (lambda: SessionGated(SessionGate.SET_PIN), 423, "set_pin"),
    (lambda: SessionGated(SessionGate.ENTER_PIN), 423, "enter_pin"),
    (lambda: SessionGated(SessionGate.IDLE_LOCKED), 423, "idle_locked"),
    (lambda: SessionGated(SessionGate.PIN_LOCKED), 423, "pin_locked"),
    (lambda: CsrfFailed(), 403, "csrf_failed"),
    (lambda: PinWrong(tries_left=3), 403, "pin_wrong"),
    (lambda: PinAlreadySet(), 409, "pin_already_set"),
    (lambda: EmailTaken("zebracanary"), 409, "email_taken"),
    (lambda: AlreadyDrafted("zebracanary"), 409, "already_drafted"),
    (lambda: NotRetryable("zebracanary"), 409, "not_retryable"),
    (lambda: DailyDraftLimit(), 429, "daily_draft_limit"),
    (lambda: DatabaseWaking("zebracanary"), 503, "database_waking"),
]


def index_of(code: str) -> int:
    return next(i for i, (_, _, c) in enumerate(CASES) if c == code)


def throwaway_app() -> FastAPI:
    app = create_app(Settings(database_url="postgresql+asyncpg://unused@localhost/unused"))
    for index, (make, _status, _code) in enumerate(CASES):

        def raiser(make: Callable[[], Exception] = make) -> None:
            raise make()

        app.add_api_route(f"/throwaway/{index}", raiser)

    def boom() -> None:
        raise RuntimeError("zebracanary")

    app.add_api_route("/throwaway/boom", boom)
    return app


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("index", "status", "code"), [(i, s, c) for i, (_, s, c) in enumerate(CASES)]
)
async def test_problem_codes_have_their_status(index: int, status: int, code: str) -> None:
    transport = httpx.ASGITransport(app=throwaway_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/throwaway/{index}")
    assert response.status_code == status
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["code"] == code
    assert body["status"] == status
    assert "zebracanary" not in response.text


@pytest.mark.asyncio
async def test_review_incomplete_lists_the_lines() -> None:
    transport = httpx.ASGITransport(app=throwaway_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/throwaway/4")
    assert response.json()["line_ids"] == ["e1-D2", "e1-A1"]


@pytest.mark.asyncio
async def test_an_unexpected_error_is_a_plain_500() -> None:
    transport = httpx.ASGITransport(app=throwaway_app(), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/throwaway/boom")
    assert response.status_code == 500
    assert "zebracanary" not in response.text


@pytest.mark.asyncio
async def test_a_wrong_pin_says_how_many_tries_are_left() -> None:
    transport = httpx.ASGITransport(app=throwaway_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/throwaway/{index_of('pin_wrong')}")
    assert response.json()["tries_left"] == 3


@pytest.mark.asyncio
async def test_a_waking_database_asks_for_a_retry_in_five_seconds() -> None:
    transport = httpx.ASGITransport(app=throwaway_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/throwaway/{index_of('database_waking')}")
    assert response.headers["retry-after"] == "5"


def test_an_open_session_is_never_a_gate_problem() -> None:
    with pytest.raises(ValueError, match="open"):
        SessionGated(SessionGate.OPEN)


@pytest.mark.asyncio
async def test_only_a_wrong_pin_carries_tries_left() -> None:
    transport = httpx.ASGITransport(app=throwaway_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/throwaway/{index_of('csrf_failed')}")
    assert "tries_left" not in response.json()
