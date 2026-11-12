"""Database engine and a liveness ping."""

import asyncio

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def create_engine(url: str) -> AsyncEngine:
    """Build an async engine that checks pooled connections before using them."""
    return create_async_engine(url, pool_pre_ping=True)


async def ping(engine: AsyncEngine, timeout_s: float) -> bool:
    """Return True if the database answers SELECT 1 within timeout_s; never raises."""
    try:
        async with asyncio.timeout(timeout_s), engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except (TimeoutError, OSError, SQLAlchemyError):
        return False
    return True
