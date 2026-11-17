"""AI usage: what each call cost, and the month's total the budget guard checks."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncEngine

from nursing_core.domain import DomainModel
from nursing_core.domain.notes import GenerationInfo
from nursing_core.storage import tables

# The live provider: its answers are the billed ones. A mock or replay answer is recorded at $0.
_BILLED_PROVIDER = "anthropic"


class MonthUsage(DomainModel):
    """One UTC calendar month of AI usage."""

    cost_usd: Decimal
    calls: int  # every answer recorded, mock and replay ones included
    billed_calls: int  # the live model's answers, the ones that cost money


class PgUsageRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def record(self, job_id: UUID | None, generation: GenerationInfo, at: datetime) -> None:
        """One row for one successful generation."""
        async with self._engine.begin() as conn:
            await conn.execute(
                insert(tables.ai_usage).values(
                    id=uuid4(),
                    job_id=job_id,
                    provider=generation.provider,
                    model=generation.model,
                    prompt_version=generation.prompt_version,
                    input_tokens=generation.input_tokens,
                    output_tokens=generation.output_tokens,
                    cost_usd=generation.cost_usd,
                    created_at=at,
                )
            )

    async def month_total(self, now: datetime) -> tuple[Decimal, int]:
        """The cost and number of calls in the UTC calendar month that contains `now`."""
        usage = await self.month_usage(now)
        return usage.cost_usd, usage.calls

    async def month_usage(self, now: datetime) -> MonthUsage:
        """The UTC calendar month that contains `now`: its cost, its calls and the billed ones."""
        start = now.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        following = (start + timedelta(days=32)).replace(day=1)
        usage = tables.ai_usage
        async with self._engine.begin() as conn:
            row = (
                await conn.execute(
                    select(
                        func.coalesce(func.sum(usage.c.cost_usd), 0),
                        func.count(),
                        func.count().filter(usage.c.provider == _BILLED_PROVIDER),
                    ).where(usage.c.created_at >= start, usage.c.created_at < following)
                )
            ).one()
        return MonthUsage(cost_usd=Decimal(row[0]), calls=row[1], billed_calls=row[2])
