"""Test databases: one migrated template per session, a fresh copy for each test.

`CREATE DATABASE ... TEMPLATE` copies a migrated database in milliseconds, so each test that
writes gets its own and never has to clean up with TRUNCATE or DELETE (the record's tables
refuse both). Used by the core and API test suites through their conftest files.
"""

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from nursing_core.storage.migrate import upgrade


def _url_for(server_url: str, database: str) -> str:
    return make_url(server_url).set(database=database).render_as_string(hide_password=False)


async def _admin(server_url: str, statement: str) -> None:
    """Run one statement outside a transaction, as CREATE and DROP DATABASE need."""
    engine = create_async_engine(server_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(text(statement))
    finally:
        await engine.dispose()


async def create_template(server_url: str) -> str:
    """Create a database migrated to head on the server at `server_url`; return its name.

    Call it once per session. The returned name is only ever used as a template, so nothing
    stays connected to it.
    """
    name = f"template_{uuid.uuid4().hex[:12]}"
    await _admin(server_url, f'CREATE DATABASE "{name}"')
    await upgrade(_url_for(server_url, name))
    return name


@asynccontextmanager
async def fresh_database(server_url: str, template: str) -> AsyncGenerator[str]:
    """Yield the URL of a new database copied from `template`; drop it on exit."""
    name = f"test_{uuid.uuid4().hex[:12]}"
    await _admin(server_url, f'CREATE DATABASE "{name}" TEMPLATE "{template}"')
    try:
        yield _url_for(server_url, name)
    finally:
        await _admin(server_url, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
