"""AI usage: what each call cost, and the month's total the budget guard checks."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncEngine

from nursing_core.domain import DomainModel
from nursing_core.domain.errors import AiBudgetReached
from nursing_core.domain.notes import GenerationInfo
from nursing_core.storage import tables

# The live provider: its answers are the billed ones. A mock or replay answer is recorded at $0.
_BILLED_PROVIDER = "anthropic"

# A hold left by a crashed call stops counting after this long.
HOLD_TTL = timedelta(minutes=15)
# One advisory lock serializes every hold, so two workers never both pass the cap.
_HOLD_LOCK = 4_815_162_342


def _month_bounds(now: datetime) -> tuple[datetime, datetime]:
    start = now.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start, (start + timedelta(days=32)).replace(day=1)


class MonthUsage(DomainModel):
    """One UTC calendar month of AI usage."""

    cost_usd: Decimal
    calls: int  # every answer recorded, mock and replay ones included
    billed_calls: int  # the live model's answers, the ones that cost money


class PgUsageRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def hold(
        self, job_id: UUID | None, amount_usd: Decimal, cap_usd: Decimal, now: datetime
    ) -> None:
        """Reserves `amount_usd` of the month's cap for a live call, or raises AiBudgetReached.

        This month's spend, the open holds and this one must stay within the cap. The check and
        the insert run under one lock, so concurrent calls see each other's holds. `record` releases
        the job's hold; one left by a crash (or with no job) expires after HOLD_TTL.
        """
        start, following = _month_bounds(now)
        usage, holds = tables.ai_usage, tables.ai_spend_hold
        async with self._engine.begin() as conn:
            await conn.execute(select(func.pg_advisory_xact_lock(_HOLD_LOCK)))
            await conn.execute(delete(holds).where(holds.c.expires_at <= now))
            # One statement, so one snapshot: a hold that a concurrent `record` turns into usage
            # is counted once, never twice and never missed.
            spent_sql = (
                select(func.coalesce(func.sum(usage.c.cost_usd), 0))
                .where(usage.c.created_at >= start, usage.c.created_at < following)
                .scalar_subquery()
            )
            held_sql = select(func.coalesce(func.sum(holds.c.amount_usd), 0)).scalar_subquery()
            spent, held = (await conn.execute(select(spent_sql, held_sql))).one()
            if Decimal(spent) + Decimal(held) + amount_usd > cap_usd:
                raise AiBudgetReached("the monthly AI cap would be passed")
            await conn.execute(
                insert(holds).values(
                    id=uuid4(),
                    job_id=job_id,
                    amount_usd=amount_usd,
                    created_at=now,
                    expires_at=now + HOLD_TTL,
                )
            )

    async def record(self, job_id: UUID | None, generation: GenerationInfo, at: datetime) -> None:
        """One row for one successful generation; the job's hold is released with it."""
        async with self._engine.begin() as conn:
            if job_id is not None:
                await conn.execute(
                    delete(tables.ai_spend_hold).where(tables.ai_spend_hold.c.job_id == job_id)
                )
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
        start, following = _month_bounds(now)
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
