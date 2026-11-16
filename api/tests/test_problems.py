"""Domain errors answer as RFC 9457 problem documents, whatever route raised them."""

from collections.abc import Callable

import httpx
import pytest
from fastapi import FastAPI
from nursing_api.app import create_app
from nursing_api.problems import NotSignedIn, PreconditionRequired
from nursing_api.settings import Settings
from nursing_core.domain.errors import (
    Forbidden,
    IdempotencyConflict,
    NoteLocked,
    NotFound,
    ReviewIncomplete,
    StaleVersion,
)

CASES: list[tuple[Callable[[], Exception], int, str]] = [
    (lambda: NotSignedIn(), 401, "not_signed_in"),
    (lambda: Forbidden("zebracanary"), 403, "forbidden"),
    (lambda: NotFound("zebracanary"), 404, "not_found"),
    (lambda: NoteLocked("zebracanary"), 409, "note_locked"),
    (lambda: ReviewIncomplete(["e1-D2", "e1-A1"]), 409, "review_incomplete"),
    (lambda: StaleVersion("zebracanary"), 412, "stale_version"),
    (lambda: IdempotencyConflict("zebracanary"), 422, "idempotency_key_reused"),
    (lambda: PreconditionRequired("If-Match"), 428, "precondition_required"),
]


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
async def test_domain_errors_are_problem_documents(index: int, status: int, code: str) -> None:
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
