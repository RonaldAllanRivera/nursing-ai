"""Alembic's environment: connect with the async engine and run the migrations online.

The URL comes from `Config.attributes["url"]` (see `storage/migrate.py`). This runs in a worker
thread with no event loop of its own, so `asyncio.run` is safe here.
"""

import asyncio

from alembic import context
from nursing_core.storage.tables import metadata
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine

config = context.config


def _migrate(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def _run() -> None:
    engine = create_async_engine(config.attributes["url"])
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_migrate)
    finally:
        await engine.dispose()


asyncio.run(_run())
