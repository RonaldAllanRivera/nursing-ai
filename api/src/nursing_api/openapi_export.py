import json
from pathlib import Path

from nursing_api.app import create_app
from nursing_api.settings import Settings

OPENAPI_PATH = Path(__file__).resolve().parents[2] / "openapi.json"


def main() -> None:
    app = create_app(Settings(database_url="postgresql+asyncpg://unused@localhost/unused"))
    OPENAPI_PATH.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
