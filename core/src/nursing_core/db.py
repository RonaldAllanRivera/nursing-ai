"""Database engine and a liveness ping."""

import asyncio
import logging
from typing import Any

import asyncpg  # pyright: ignore[reportMissingTypeStubs]
from sqlalchemy import event, text
from sqlalchemy.engine import Dialect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from nursing_core.domain.errors import DatabaseWaking

logger = logging.getLogger(__name__)


# What a waking database is told apart by: a connect that takes too long, or a server that says
# it is still starting up (SQLSTATE 57P03).
_WAKING_MESSAGE = "the database is waking up"
_WAKING = (TimeoutError, asyncpg.CannotConnectNowError)


def create_engine(
    url: str, *, null_pool: bool = False, connect_timeout_s: float = 10.0
) -> AsyncEngine:
    """Build an async engine that checks pooled connections before using them.

    A connect that times out, or meets a database that is still resuming, raises `DatabaseWaking`
    (the message is fixed: a driver's can carry the host or the port). Any other connect error
    passes through. `null_pool` keeps no idle connections (Lambda freezes between requests).
    """
    if null_pool:
        engine = create_async_engine(
            url, poolclass=NullPool, connect_args={"timeout": connect_timeout_s}
        )
    else:
        engine = create_async_engine(
            url, pool_pre_ping=True, connect_args={"timeout": connect_timeout_s}
        )

    @event.listens_for(engine.sync_engine, "do_connect")
    def _connect(  # pyright: ignore[reportUnusedFunction]
        dialect: Dialect, _record: object, cargs: tuple[Any, ...], cparams: dict[str, Any]
    ) -> Any:
        try:
            return dialect.connect(*cargs, **cparams)
        except _WAKING:
            raise DatabaseWaking(_WAKING_MESSAGE) from None
        except Exception as error:
            # The asyncpg adapter re-raises a server error as its own class, with the original
            # as the cause.
            if isinstance(error.__cause__, asyncpg.CannotConnectNowError):
                raise DatabaseWaking(_WAKING_MESSAGE) from None
            raise

    return engine


async def ping(engine: AsyncEngine, timeout_s: float) -> bool:
    """Return True if the database answers SELECT 1 within timeout_s; never raises."""
    try:
        async with asyncio.timeout(timeout_s), engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except (TimeoutError, OSError, SQLAlchemyError, DatabaseWaking) as error:
        # The class only: a driver's message can carry the host, the port or part of the URL.
        logger.warning("database ping failed", extra={"error_class": type(error).__name__})
        return False
    return True
