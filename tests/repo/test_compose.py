"""The Postgres image is pinned to one exact tag; the API starts on a migrated, seeded database."""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from conftest import compose_db_image

ROOT = Path(__file__).resolve().parents[2]


def services() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    return data["services"]


def test_db_image_is_an_exact_pgvector_pg17_tag() -> None:
    assert re.fullmatch(r"pgvector/pgvector:\d+\.\d+\.\d+-pg17-bookworm", compose_db_image())


def test_the_api_starts_only_after_the_migration_and_the_seed() -> None:
    # The API's startup reads the job table, so an unmigrated database stops it from starting.
    found = services()
    done = {"condition": "service_completed_successfully"}
    assert found["migrate"]["depends_on"] == {"db": {"condition": "service_healthy"}}
    assert found["seed"]["depends_on"] == {"migrate": done}
    assert found["api"]["depends_on"]["migrate"] == done
    assert found["api"]["depends_on"]["seed"] == done


@pytest.mark.parametrize(
    ("service", "module"),
    [("migrate", "nursing_core.storage.migrate"), ("seed", "nursing_core.storage.seed")],
)
def test_each_one_shot_job_runs_once_in_the_apis_image_on_its_database(
    service: str, module: str
) -> None:
    found = services()
    job, api = found[service], found["api"]
    assert job["command"] == ["python", "-m", module]
    assert job["restart"] == "no"
    assert job["build"] == api["build"]
    assert job["environment"] == {"DATABASE_URL": api["environment"]["DATABASE_URL"]}
    assert "ports" not in job


def test_the_api_gets_its_ai_mode_from_the_environment_and_never_the_key_or_the_cap() -> None:
    # `make e2e AI_MODE=replay` runs the API on recordings; live mode stays unsupported in Compose.
    env = services()["api"]["environment"]
    assert env["AI_MODE"] == "${AI_MODE:-mock}"
    assert "ANTHROPIC_API_KEY" not in env
    assert "AI_MONTHLY_CAP_USD" not in env


def test_api_container_listens_on_8080() -> None:
    # The Lambda Web Adapter forwards to 8080, so the image listens there everywhere, Compose too.
    dockerfile = (ROOT / "api" / "Dockerfile").read_text()
    assert "EXPOSE 8080\n" in dockerfile
    assert dockerfile.rstrip().endswith(
        'CMD ["uvicorn", "--factory", "nursing_api.app:create_app", '
        '"--host", "0.0.0.0", "--port", "8080"]'
    )
    api = services()["api"]
    assert api["ports"] == ["127.0.0.1:${API_PORT:-8000}:8080"]
    assert "http://127.0.0.1:8080/api/v1/health" in " ".join(api["healthcheck"]["test"])


def test_the_api_gets_the_site_url_and_the_google_settings_from_dotenv() -> None:
    # Compose fills `${X:-}` from .env; a name .env leaves out arrives empty, which reads as unset.
    env = services()["api"]["environment"]
    assert env["APP_ENV"] == "${APP_ENV:-dev}"
    assert env["SITE_URL"] == "http://localhost:${WEB_PORT:-5173}"
    for name in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "BOOTSTRAP_ADMIN_EMAIL"):
        assert env[name] == f"${{{name}:-}}"
