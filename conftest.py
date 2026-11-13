"""Root pytest fixtures shared by every package."""

import asyncio
import contextlib
import os
import socket
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
import yaml
from testcontainers.community.postgres import PostgresContainer

ROOT = Path(__file__).resolve().parent

# Docker Desktop for Linux refuses the reaper container's socket mount; the fixture below
# stops its container itself, so the reaper is not needed.
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")


def compose_db_image() -> str:
    """Return the Postgres image pinned in docker-compose.yml."""
    data: object = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    assert isinstance(data, dict)
    services: object = data["services"]  # pyright: ignore[reportUnknownVariableType]
    assert isinstance(services, dict)
    db: object = services["db"]  # pyright: ignore[reportUnknownVariableType]
    assert isinstance(db, dict)
    image: object = db["image"]  # pyright: ignore[reportUnknownVariableType]
    assert isinstance(image, str)
    return image


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return ROOT


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    with PostgresContainer(compose_db_image(), driver="asyncpg") as pg:
        yield pg.get_connection_url()


@pytest.fixture
def free_port() -> int:
    """A local port that nothing listens on."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
    return port


@pytest_asyncio.fixture
async def silent_port() -> AsyncIterator[int]:
    """A local port that accepts connections and never answers; each one is closed afterwards."""
    release = asyncio.Event()
    writers: list[asyncio.StreamWriter] = []

    async def silent(_reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writers.append(writer)
        await release.wait()

    server = await asyncio.start_server(silent, "127.0.0.1", 0)
    port: int = server.sockets[0].getsockname()[1]
    try:
        yield port
    finally:
        release.set()
        for writer in writers:
            writer.close()
            with contextlib.suppress(ConnectionError):
                await writer.wait_closed()
        server.close()
        await server.wait_closed()
