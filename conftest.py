"""Root pytest fixtures shared by every package."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from testcontainers.community.postgres import PostgresContainer

ROOT = Path(__file__).resolve().parent

# Docker Desktop for Linux refuses the reaper container's socket mount; the fixture below
# stops its container itself, so the reaper is not needed.
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")


def compose_db_image() -> str:
    """Return the Postgres image pinned in docker-compose.yml."""
    data: object = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    assert isinstance(data, dict)
    services: object = data["services"]  # pyright: ignore[reportUnknownVariableType]
    assert isinstance(services, dict)
    db: object = services["db"]  # pyright: ignore[reportUnknownVariableType]
    assert isinstance(db, dict)
    image: object = db["image"]  # pyright: ignore[reportUnknownVariableType]
    assert isinstance(image, str)
    return image


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return ROOT


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    with PostgresContainer(compose_db_image(), driver="asyncpg") as pg:
        yield pg.get_connection_url()
