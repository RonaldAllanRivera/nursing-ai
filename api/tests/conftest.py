"""Fixtures for the API tests: a migrated and seeded template database, a fresh copy per test."""

import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from nursing_core.clock import FixedClock
from nursing_core.db import create_engine
from nursing_core.storage.seed import seed
from nursing_core.storage.testdb import create_template, fresh_database
from sqlalchemy.engine import make_url

from .helpers import NOW, MutableClock, client_for, running_app


async def _migrated_and_seeded(server_url: str) -> str:
    name = await create_template(server_url)
    url = make_url(server_url).set(database=name).render_as_string(hide_password=False)
    engine = create_engine(url)
    try:
        await seed(engine, FixedClock(NOW))
    finally:
        # Postgres refuses CREATE DATABASE ... TEMPLATE while the template has connections.
        await engine.dispose()
    return name


@pytest.fixture(scope="session")
def template_database(postgres_url: str) -> str:
    """A database migrated to head and seeded with the demo data, once for the whole session."""
    return asyncio.run(_migrated_and_seeded(postgres_url))


@pytest_asyncio.fixture
async def database_url(postgres_url: str, template_database: str) -> AsyncIterator[str]:
    """A private copy of the seeded template, dropped after the test."""
    async with fresh_database(postgres_url, template_database) as url:
        yield url


@pytest.fixture
def clock() -> MutableClock:
    return MutableClock(NOW)


@pytest_asyncio.fixture
async def app(database_url: str, clock: MutableClock) -> AsyncIterator[FastAPI]:
    async with running_app(database_url, clock) as running:
        yield running


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with client_for(app) as http:
        yield http
