"""AI usage against a real migrated database: what each month cost, and which calls were billed."""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from nursing_core.clock import FixedClock
from nursing_core.domain.errors import AiBudgetReached
from nursing_core.storage import tables
from nursing_core.storage.repositories import PgNoteRepository
from nursing_core.storage.usage import HOLD_TTL, MonthUsage, PgUsageRepository
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from .world import NOW, build_world, generation, rough_note

CLOCK = FixedClock(NOW)


@pytest.mark.asyncio
async def test_usage_month_total_covers_the_utc_calendar_month(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    repo = PgUsageRepository(engine)
    assert await repo.month_total(NOW) == (Decimal(0), 0)
    rough_repo = PgNoteRepository(engine, CLOCK)
    _, job = await rough_repo.add_rough_note(rough_note(world), "k", "a" * 64)
    info = generation()
    at = datetime(2026, 11, 3, tzinfo=UTC)
    await repo.record(job.id, info, at)
    await repo.record(None, info, datetime(2026, 11, 30, 23, 59, 59, tzinfo=UTC))
    await repo.record(None, info, datetime(2026, 10, 31, 23, 59, 59, tzinfo=UTC))
    await repo.record(None, info, datetime(2026, 12, 1, tzinfo=UTC))

    total, calls = await repo.month_total(datetime(2026, 11, 15, 12, tzinfo=UTC))

    assert (total, calls) == (info.cost_usd * 2, 2)
    assert await repo.month_total(datetime(2026, 12, 20, tzinfo=UTC)) == (info.cost_usd, 1)
    # Only the live model's answers are billed: a mock or replay answer is recorded at $0.
    billed = info.model_copy(update={"provider": "anthropic"})
    await repo.record(None, billed, at)
    assert await repo.month_usage(datetime(2026, 11, 15, 12, tzinfo=UTC)) == MonthUsage(
        cost_usd=info.cost_usd * 3, calls=3, billed_calls=1
    )
    assert await repo.month_usage(datetime(2026, 9, 1, tzinfo=UTC)) == MonthUsage(
        cost_usd=Decimal(0), calls=0, billed_calls=0
    )
    async with engine.connect() as conn:
        row = (
            await conn.execute(select(tables.ai_usage).where(tables.ai_usage.c.job_id == job.id))
        ).one()
    assert (row.provider, row.model, row.prompt_version) == (
        info.provider,
        info.model,
        info.prompt_version,
    )
    assert (row.input_tokens, row.output_tokens, row.created_at) == (120, 80, at)


async def _hold_rows(engine: AsyncEngine) -> list[tuple[UUID | None, Decimal]]:
    async with engine.connect() as conn:
        rows = (await conn.execute(select(tables.ai_spend_hold))).all()
    return [(row.job_id, row.amount_usd) for row in rows]


@pytest.mark.asyncio
async def test_two_concurrent_guards_pass_only_one_under_the_cap(engine: AsyncEngine) -> None:
    repo = PgUsageRepository(engine)
    cap = Decimal("1.00")
    # Each hold fits the cap alone; together they do not.
    results = await asyncio.gather(
        repo.hold(None, Decimal("0.60"), cap, NOW),
        repo.hold(None, Decimal("0.60"), cap, NOW),
        return_exceptions=True,
    )
    refused = [r for r in results if isinstance(r, AiBudgetReached)]
    passed = [r for r in results if r is None]
    assert (len(passed), len(refused)) == (1, 1)
    assert await _hold_rows(engine) == [(None, Decimal("0.600000"))]


@pytest.mark.asyncio
async def test_a_hold_counts_the_months_spend_and_the_open_holds(engine: AsyncEngine) -> None:
    repo = PgUsageRepository(engine)
    info = generation().model_copy(update={"cost_usd": Decimal("0.30")})
    await repo.record(None, info, NOW)
    await repo.hold(None, Decimal("0.30"), Decimal("1.00"), NOW)
    await repo.hold(None, Decimal("0.40"), Decimal("1.00"), NOW)  # exactly the cap: allowed
    with pytest.raises(AiBudgetReached):
        await repo.hold(None, Decimal("0.01"), Decimal("1.00"), NOW)


@pytest.mark.asyncio
async def test_recorded_usage_releases_the_hold(engine: AsyncEngine) -> None:
    world = await build_world(engine)
    repo = PgUsageRepository(engine)
    notes = PgNoteRepository(engine, CLOCK)
    _, job = await notes.add_rough_note(rough_note(world), "k", "a" * 64)
    _, other = await notes.add_rough_note(rough_note(world), "k2", "b" * 64)
    await repo.hold(job.id, Decimal("0.50"), Decimal("1.00"), NOW)
    await repo.hold(other.id, Decimal("0.20"), Decimal("1.00"), NOW)

    await repo.record(job.id, generation(), NOW)

    assert await _hold_rows(engine) == [(other.id, Decimal("0.200000"))]


@pytest.mark.asyncio
async def test_expired_hold_no_longer_counts(engine: AsyncEngine) -> None:
    repo = PgUsageRepository(engine)
    cap = Decimal("1.00")
    await repo.hold(None, Decimal("0.90"), cap, NOW)
    with pytest.raises(AiBudgetReached):
        await repo.hold(None, Decimal("0.90"), cap, NOW + HOLD_TTL - timedelta(seconds=1))

    await repo.hold(None, Decimal("0.90"), cap, NOW + HOLD_TTL)

    async with engine.connect() as conn:
        rows = (await conn.execute(select(tables.ai_spend_hold))).all()
    assert len(rows) == 1  # the expired one was deleted
    assert rows[0].expires_at == NOW + HOLD_TTL + HOLD_TTL
