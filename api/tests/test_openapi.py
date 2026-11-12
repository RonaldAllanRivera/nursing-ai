import json
from pathlib import Path

from nursing_api.app import create_app
from nursing_api.settings import Settings


def test_committed_openapi_matches_app(repo_root: Path) -> None:
    committed = json.loads((repo_root / "api" / "openapi.json").read_text())
    app = create_app(Settings(database_url="postgresql+asyncpg://unused@localhost/unused"))
    assert committed == app.openapi()
