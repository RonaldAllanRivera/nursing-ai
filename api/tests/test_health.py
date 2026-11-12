import socket
import time

import httpx
import pytest
from nursing_api.app import create_app
from nursing_api.settings import Settings


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


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
async def test_health_503_when_database_down() -> None:
    url = f"postgresql+asyncpg://app:x@127.0.0.1:{_free_port()}/app"
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
