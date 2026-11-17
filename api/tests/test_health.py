import time
from typing import Any, Literal

import httpx
import pytest
from nursing_api.app import create_app
from nursing_api.settings import Settings
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine


@pytest.mark.asyncio
async def test_health_200_when_database_up(postgres_url: str) -> None:
    app = create_app(Settings(database_url=postgres_url))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "database": "ok"}


@pytest.mark.asyncio
async def test_health_503_when_database_down(free_port: int) -> None:
    url = f"postgresql+asyncpg://app:x@127.0.0.1:{free_port}/app"
    app = create_app(Settings(database_url=url))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            start = time.monotonic()
            response = await client.get("/api/v1/health")
            elapsed = time.monotonic() - start
    assert response.status_code == 503
    assert response.json() == {"status": "unhealthy", "database": "unreachable"}
    assert elapsed < 3


@pytest.mark.asyncio
async def test_health_503_when_database_never_answers(silent_port: int) -> None:
    url = f"postgresql+asyncpg://app:x@127.0.0.1:{silent_port}/app"
    app = create_app(Settings(database_url=url, db_ping_timeout_s=0.5))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            start = time.monotonic()
            response = await client.get("/api/v1/health")
            elapsed = time.monotonic() - start
    assert response.status_code == 503
    assert response.json() == {"status": "unhealthy", "database": "unreachable"}
    assert elapsed < 1.5


@pytest.mark.asyncio
@pytest.mark.parametrize("app_env", ["demo", "prod"])
async def test_health_in_demo_and_prod_never_touches_the_database(
    free_port: int, app_env: Literal["demo", "prod"]
) -> None:
    # A crawler polling /health must never wake a paused database, so live the route answers
    # without opening a connection; the deep check is the ops function's `smoke` task.
    url = f"postgresql+asyncpg://app:x@127.0.0.1:{free_port}/app"
    app = create_app(Settings(database_url=url, app_env=app_env))
    attempts: list[str] = []
    async with app.router.lifespan_context(app):
        engine: AsyncEngine = app.state.engine

        @event.listens_for(engine.sync_engine, "do_connect")
        def count(*_args: Any) -> None:  # pyright: ignore[reportUnusedFunction]
            attempts.append("connect")

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "database": "not_checked"}
    assert attempts == []
