"""Run the Alembic migrations from code, with no `alembic.ini`.

`upgrade` is async so a test or the API's startup can call it from inside a running event loop:
Alembic itself is synchronous, so it runs in a worker thread, where `migrations/env.py` opens its
own event loop for the async engine.
"""

import asyncio
import os
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

MIGRATIONS = Path(__file__).resolve().parent / "migrations"


def make_config(url: str) -> Config:
    """An Alembic config built in code; the database URL travels in `attributes`, not the ini."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.set_main_option("path_separator", "os")
    config.attributes["url"] = url
    return config


async def upgrade(url: str, revision: str = "head") -> None:
    """Bring the database at `url` (a `postgresql+asyncpg://` URL) up to `revision`."""
    await asyncio.to_thread(command.upgrade, make_config(url), revision)


def main() -> None:
    """`python -m nursing_core.storage.migrate`: upgrade the database in `DATABASE_URL`."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set")
    asyncio.run(upgrade(url))


if __name__ == "__main__":
    main()
