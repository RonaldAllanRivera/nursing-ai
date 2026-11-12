"""Tests for the database ping."""

import asyncio
import socket
import time

import pytest
from nursing_core.db import create_engine, ping


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
    return port


@pytest.mark.asyncio
async def test_ping_true_for_live_database(postgres_url: str) -> None:
    engine = create_engine(postgres_url)
    try:
        assert await ping(engine, timeout_s=5.0) is True
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_ping_false_when_nothing_listens() -> None:
    engine = create_engine(f"postgresql+asyncpg://app:x@127.0.0.1:{_free_port()}/app")
    started = time.monotonic()
    try:
        assert await ping(engine, timeout_s=1.0) is False
    finally:
        await engine.dispose()
    assert time.monotonic() - started < 3.0


@pytest.mark.asyncio
async def test_ping_false_when_server_never_answers() -> None:
    async def silent(_reader: asyncio.StreamReader, _writer: asyncio.StreamWriter) -> None:
        await asyncio.sleep(30)

    server = await asyncio.start_server(silent, "127.0.0.1", 0)
    port: int = server.sockets[0].getsockname()[1]
    engine = create_engine(f"postgresql+asyncpg://app:x@127.0.0.1:{port}/app")
    started = time.monotonic()
    try:
        assert await ping(engine, timeout_s=0.5) is False
    finally:
        await engine.dispose()
        server.close()
    assert time.monotonic() - started < 1.5
