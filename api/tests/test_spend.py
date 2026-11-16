"""`python -m nursing_api.spend`: the report of this month's AI spend."""

import asyncio
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from nursing_api.spend import main, render
from nursing_core.db import create_engine
from nursing_core.domain.notes import GenerationInfo
from nursing_core.storage.repositories import PgUsageRepository
from sqlalchemy.engine import make_url

CANARY_KEY = "sk-ant-canary-not-a-real-key"
SETTING_NAMES = (
    "APP_ENV",
    "DATABASE_URL",
    "DB_PING_TIMEOUT_S",
    "AI_MODE",
    "AI_MONTHLY_CAP_USD",
    "ANTHROPIC_API_KEY",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in SETTING_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", CANARY_KEY)


def _lines(capsys: pytest.CaptureFixture[str]) -> list[str]:
    out = capsys.readouterr()
    assert CANARY_KEY not in out.out + out.err
    return out.out.splitlines()


def _generation(cost: str) -> GenerationInfo:
    return GenerationInfo(
        provider="fake",
        model="claude-opus-5-5",
        prompt_version="p1",
        input_tokens=10,
        output_tokens=20,
        cost_usd=Decimal(cost),
        latency_ms=1,
    )


def _month_label(now: datetime) -> str:
    return f"{now.year}-{now.month:02d}"


def test_render_with_no_cap_and_no_usage() -> None:
    assert render("mock", None, Decimal(0), 0, "2026-11") == [
        "AI_MODE=mock",
        "AI_MONTHLY_CAP_USD=not set",
        "AI usage 2026-11 (UTC): $0.000000 over 0 calls",
    ]


def test_render_with_cap_and_usage_and_one_call() -> None:
    lines = render("live", Decimal("25.50"), Decimal("0.1234567"), 1, "2026-11")
    assert lines[1] == "AI_MONTHLY_CAP_USD=25.50"
    assert lines[2] == "AI usage 2026-11 (UTC): $0.123457 over 1 call"


def test_render_without_usage_adds_one_plain_line() -> None:
    lines = render("mock", None, None, None, "2026-11", unread="Run `make up`.")
    assert lines == ["AI_MODE=mock", "AI_MONTHLY_CAP_USD=not set", "Run `make up`."]


@pytest.mark.asyncio
async def test_mock_with_no_usage(
    database_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
    assert await asyncio.to_thread(main, []) == 0
    assert _lines(capsys) == [
        "AI_MODE=mock",
        "AI_MONTHLY_CAP_USD=not set",
        f"AI usage {_month_label(datetime.now(UTC))} (UTC): $0.000000 over 0 calls",
    ]


@pytest.mark.asyncio
async def test_only_this_months_rows_count(
    database_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    now = datetime.now(UTC)
    last_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=1)
    engine = create_engine(database_url)
    try:
        usage = PgUsageRepository(engine)
        await usage.record(None, _generation("0.100000"), now)
        await usage.record(None, _generation("0.250000"), now)
        await usage.record(None, _generation("9.000000"), last_month)
    finally:
        await engine.dispose()
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("AI_MODE", "replay")
    monkeypatch.setenv("AI_MONTHLY_CAP_USD", "20")
    assert await asyncio.to_thread(main, []) == 0
    assert _lines(capsys) == [
        "AI_MODE=replay",
        "AI_MONTHLY_CAP_USD=20",
        f"AI usage {_month_label(now)} (UTC): $0.350000 over 2 calls",
    ]


@pytest.mark.asyncio
async def test_unreachable_database_prints_one_line_and_exits_zero(
    free_port: int, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(
        "DATABASE_URL", f"postgresql+asyncpg://app:secret-pw@127.0.0.1:{free_port}/app"
    )
    monkeypatch.setenv("DB_PING_TIMEOUT_S", "2")
    assert await asyncio.to_thread(main, []) == 0
    lines = _lines(capsys)
    assert lines[:2] == ["AI_MODE=mock", "AI_MONTHLY_CAP_USD=not set"]
    assert len(lines) == 3
    assert "make up" in lines[2]
    assert "secret-pw" not in lines[2]
    assert str(free_port) not in lines[2]


@pytest.mark.asyncio
async def test_silent_database_is_bounded_by_the_timeout(
    silent_port: int, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DATABASE_URL", f"postgresql+asyncpg://app:x@127.0.0.1:{silent_port}/app")
    monkeypatch.setenv("DB_PING_TIMEOUT_S", "0.5")
    started = asyncio.get_running_loop().time()
    assert await asyncio.to_thread(main, []) == 0
    assert asyncio.get_running_loop().time() - started < 5
    lines = _lines(capsys)
    assert len(lines) == 3
    assert "make up" in lines[2]


def test_missing_database_url_still_reports_mode_and_cap(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("AI_MODE", "replay")
    monkeypatch.setenv("AI_MONTHLY_CAP_USD", "5")
    assert main([]) == 0
    lines = _lines(capsys)
    assert lines[:2] == ["AI_MODE=replay", "AI_MONTHLY_CAP_USD=5"]
    assert len(lines) == 3
    assert "DATABASE_URL" in lines[2]
    assert "make up" in lines[2]


@pytest.mark.asyncio
async def test_unmigrated_database_says_to_migrate(
    postgres_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The server's default `test` database has no tables: nothing has migrated it.
    url = make_url(postgres_url).set(database="postgres").render_as_string(hide_password=False)
    monkeypatch.setenv("DATABASE_URL", url)
    assert await asyncio.to_thread(main, []) == 0
    lines = _lines(capsys)
    assert len(lines) == 3
    assert "make migrate" in lines[2]


def test_invalid_setting_exits_one_without_echoing_values(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("AI_MODE", "bogus-value")
    assert main([]) == 1
    out = capsys.readouterr()
    assert "bogus-value" not in out.out + out.err
    assert CANARY_KEY not in out.out + out.err


def test_python_dash_m_runs_and_hides_the_key() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "nursing_api.spend"],
        env={"PATH": "/usr/bin:/bin", "ANTHROPIC_API_KEY": CANARY_KEY, "AI_MODE": "mock"},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.splitlines()[:2] == ["AI_MODE=mock", "AI_MONTHLY_CAP_USD=not set"]
    assert CANARY_KEY not in result.stdout + result.stderr
