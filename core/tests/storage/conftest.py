"""Fixtures for the storage tests: one migrated template database, a fresh copy per test."""

import asyncio
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from nursing_core.db import create_engine
from nursing_core.storage.testdb import create_template, fresh_database
from sqlalchemy.ext.asyncio import AsyncEngine


@pytest.fixture(scope="session")
def template_database(postgres_url: str) -> str:
    """The name of a database migrated to head once for the whole session."""
    return asyncio.run(create_template(postgres_url))


@pytest_asyncio.fixture
async def database_url(postgres_url: str, template_database: str) -> AsyncIterator[str]:
    """A private copy of the migrated template, dropped after the test."""
    async with fresh_database(postgres_url, template_database) as url:
        yield url


@pytest_asyncio.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(database_url)
    try:
        yield engine
    finally:
        await engine.dispose()
