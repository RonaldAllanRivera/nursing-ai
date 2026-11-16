"""`python -m nursing_api.spend`: this month's AI spend, read from the `ai_usage` table.

A report, not a gate: when the usage can't be read it says so in one plain line and still exits 0.
It prints the mode, the cap and the usage only. The API key is never read into the output, and
an exception's text (a driver's message can carry the host or part of the URL) is never printed.
"""

import asyncio
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

from nursing_core.db import create_engine
from nursing_core.storage.repositories import MonthUsage, PgUsageRepository
from pydantic import ValidationError
from sqlalchemy.exc import ProgrammingError

from .settings import Settings

NO_URL = "AI usage not read: DATABASE_URL is not set. Run `make up`, then try again."
NO_DATABASE = "AI usage not read: the database is not reachable. Run `make up`, then try again."
NOT_MIGRATED = "AI usage not read: the database has no usage table yet. Run `make migrate`."


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}{'' if number == 1 else 's'}"


def render(
    mode: str,
    cap: Decimal | None,
    usage: MonthUsage | None,
    month: str,
    *,
    unread: str | None = None,
) -> list[str]:
    """The report's lines. `unread` (when the usage couldn't be read) replaces the usage line.

    The cost is spread over the billed calls only: a mock or replay draft is counted in all but
    costs nothing.
    """
    lines = [f"AI_MODE={mode}", f"AI_MONTHLY_CAP_USD={'not set' if cap is None else cap}"]
    if unread is not None or usage is None:
        lines.append(unread or NO_DATABASE)
    else:
        billed = _count(usage.billed_calls, "billed call")
        drafts = _count(usage.calls, "draft")
        lines.append(
            f"AI usage {month} (UTC): ${usage.cost_usd:.6f} over {billed} ({drafts} in all)"
        )
    return lines


async def read_usage(url: str, timeout_s: float, now: datetime) -> MonthUsage:
    """This UTC month's usage; the connect and the query share one time limit."""
    engine = create_engine(url)
    try:
        async with asyncio.timeout(timeout_s):
            return await PgUsageRepository(engine).month_usage(now)
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    """Print the report; 0 whenever it could be produced, 1 when a setting is invalid."""
    del argv  # no options yet
    try:
        # The URL is optional here: a missing one is reported, not a startup failure.
        settings = Settings(database_url=os.environ.get("DATABASE_URL", ""))
    except ValidationError:
        # Never the error itself: pydantic echoes the offending value.
        print("Settings are invalid: check AI_MODE, AI_MONTHLY_CAP_USD and DB_PING_TIMEOUT_S.")
        return 1
    now = datetime.now(UTC)
    month = f"{now.year}-{now.month:02d}"
    mode, cap = settings.ai_mode, settings.ai_monthly_cap_usd
    if not settings.database_url:
        print("\n".join(render(mode, cap, None, month, unread=NO_URL)))
        return 0
    try:
        usage = asyncio.run(read_usage(settings.database_url, settings.db_ping_timeout_s, now))
    except ProgrammingError:
        # The server answered but has no `ai_usage` table.
        print("\n".join(render(mode, cap, None, month, unread=NOT_MIGRATED)))
        return 0
    except Exception:  # a report never fails on the database; the error text is not shown
        print("\n".join(render(mode, cap, None, month, unread=NO_DATABASE)))
        return 0
    print("\n".join(render(mode, cap, usage, month)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
