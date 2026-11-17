"""AI usage against a real migrated database: what each month cost, and which calls were billed."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from nursing_core.clock import FixedClock
from nursing_core.storage import tables
from nursing_core.storage.repositories import PgNoteRepository
from nursing_core.storage.usage import MonthUsage, PgUsageRepository
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
