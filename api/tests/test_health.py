import asyncio
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


@pytest.mark.asyncio
async def test_health_503_when_database_never_answers() -> None:
    release = asyncio.Event()

    async def silent(_reader: asyncio.StreamReader, _writer: asyncio.StreamWriter) -> None:
        await release.wait()

    server = await asyncio.start_server(silent, "127.0.0.1", 0)
    port: int = server.sockets[0].getsockname()[1]
    url = f"postgresql+asyncpg://app:x@127.0.0.1:{port}/app"
    app = create_app(Settings(database_url=url, db_ping_timeout_s=0.5))
    try:
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                start = time.monotonic()
                response = await client.get("/api/v1/health")
                elapsed = time.monotonic() - start
    finally:
        release.set()
        server.close()
        await server.wait_closed()
    assert response.status_code == 503
    assert response.json() == {"status": "unhealthy", "database": "unreachable"}
    assert elapsed < 1.5
