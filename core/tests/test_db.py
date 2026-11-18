"""Tests for the database ping."""

import logging
import time

import asyncpg  # pyright: ignore[reportMissingTypeStubs]
import pytest
from nursing_core.db import create_engine, ping
from nursing_core.domain.errors import DatabaseWaking
from sqlalchemy import text


@pytest.mark.asyncio
async def test_ping_true_for_live_database(postgres_url: str) -> None:
    engine = create_engine(postgres_url)
    try:
        assert await ping(engine, timeout_s=5.0) is True
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_ping_false_when_nothing_listens(free_port: int) -> None:
    engine = create_engine(f"postgresql+asyncpg://app:x@127.0.0.1:{free_port}/app")
    started = time.monotonic()
    try:
        assert await ping(engine, timeout_s=1.0) is False
    finally:
        await engine.dispose()
    assert time.monotonic() - started < 3.0


@pytest.mark.asyncio
async def test_ping_failure_logs_the_exception_class_only(
    free_port: int, caplog: pytest.LogCaptureFixture
) -> None:
    engine = create_engine(f"postgresql+asyncpg://app:x@127.0.0.1:{free_port}/app")
    try:
        with caplog.at_level(logging.DEBUG):
            assert await ping(engine, timeout_s=1.0) is False
    finally:
        await engine.dispose()
    [record] = [r for r in caplog.records if r.name == "nursing_core.db"]
    assert record.getMessage() == "database ping failed"
    assert getattr(record, "error_class", None) in {"ConnectionRefusedError", "OSError"}
    assert record.exc_info is None
    assert str(free_port) not in caplog.text
    assert "127.0.0.1" not in caplog.text


@pytest.mark.asyncio
async def test_ping_false_when_server_never_answers(silent_port: int) -> None:
    engine = create_engine(f"postgresql+asyncpg://app:x@127.0.0.1:{silent_port}/app")
    started = time.monotonic()
    try:
        assert await ping(engine, timeout_s=0.5) is False
    finally:
        await engine.dispose()
    assert time.monotonic() - started < 1.5


@pytest.mark.asyncio
async def test_a_connect_that_never_answers_is_a_waking_database(silent_port: int) -> None:
    engine = create_engine(
        f"postgresql+asyncpg://app:x@127.0.0.1:{silent_port}/app", connect_timeout_s=0.5
    )
    started = time.monotonic()
    try:
        with pytest.raises(DatabaseWaking) as raised:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
    finally:
        await engine.dispose()
    assert time.monotonic() - started < 2.0
    assert str(silent_port) not in str(raised.value)
    assert "127.0.0.1" not in str(raised.value)


@pytest.mark.asyncio
async def test_a_resuming_database_is_a_waking_database(
    free_port: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def starting_up(*_args: object, **_kwargs: object) -> object:
        raise asyncpg.CannotConnectNowError("the database system is starting up")

    monkeypatch.setattr(asyncpg, "connect", starting_up)
    engine = create_engine(f"postgresql+asyncpg://app:x@127.0.0.1:{free_port}/app")
    try:
        with pytest.raises(DatabaseWaking) as raised:
            async with engine.connect():
                pass
    finally:
        await engine.dispose()
    assert "starting up" not in str(raised.value)
    assert str(free_port) not in str(raised.value)


@pytest.mark.asyncio
async def test_a_refused_connect_is_not_a_waking_database(free_port: int) -> None:
    engine = create_engine(f"postgresql+asyncpg://app:x@127.0.0.1:{free_port}/app")
    try:
        with pytest.raises(OSError, match=r".") as raised:
            async with engine.connect():
                pass
    finally:
        await engine.dispose()
    assert not isinstance(raised.value, DatabaseWaking)


@pytest.mark.asyncio
async def test_ping_false_when_the_database_is_waking(silent_port: int) -> None:
    engine = create_engine(
        f"postgresql+asyncpg://app:x@127.0.0.1:{silent_port}/app", connect_timeout_s=0.3
    )
    try:
        assert await ping(engine, timeout_s=3.0) is False
    finally:
        await engine.dispose()
