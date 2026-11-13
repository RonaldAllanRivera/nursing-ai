from decimal import Decimal
from pathlib import Path

import pytest
from nursing_api.settings import Settings
from pydantic import ValidationError

SETTING_NAMES = (
    "APP_ENV",
    "DATABASE_URL",
    "DB_PING_TIMEOUT_S",
    "AI_MODE",
    "AI_MONTHLY_CAP_USD",
    "ANTHROPIC_API_KEY",
)
CANARY_KEY = "sk-ant-canary-not-a-real-key"


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> pytest.MonkeyPatch:
    """An empty working folder and no setting in the environment except DATABASE_URL."""
    for name in SETTING_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://app:x@127.0.0.1:1/app")
    return monkeypatch


def test_dotenv_in_working_directory_is_ignored(clean_env: pytest.MonkeyPatch) -> None:
    Path(".env").write_text(f"AI_MODE=live\nANTHROPIC_API_KEY={CANARY_KEY}\n")
    settings = Settings()  # pyright: ignore[reportCallIssue]
    assert settings.ai_mode == "mock"
    assert settings.anthropic_api_key is None


def test_settings_have_safe_defaults(clean_env: pytest.MonkeyPatch) -> None:
    settings = Settings()  # pyright: ignore[reportCallIssue]
    assert settings.app_env == "dev"
    assert settings.ai_mode == "mock"
    assert settings.ai_monthly_cap_usd is None
    assert settings.db_ping_timeout_s == 2.0


def test_ai_settings_come_from_the_environment(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("AI_MODE", "replay")
    clean_env.setenv("AI_MONTHLY_CAP_USD", "15")
    clean_env.setenv("APP_ENV", "test")
    settings = Settings()  # pyright: ignore[reportCallIssue]
    assert settings.ai_mode == "replay"
    assert settings.ai_monthly_cap_usd == Decimal("15")
    assert settings.app_env == "test"


def test_api_key_never_in_repr(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("ANTHROPIC_API_KEY", CANARY_KEY)
    settings = Settings()  # pyright: ignore[reportCallIssue]
    assert settings.anthropic_api_key is not None
    assert settings.anthropic_api_key.get_secret_value() == CANARY_KEY
    assert CANARY_KEY not in repr(settings)
    assert CANARY_KEY not in str(settings.model_dump())


@pytest.mark.parametrize("timeout", ["0", "-1"])
def test_ping_timeout_must_be_positive(clean_env: pytest.MonkeyPatch, timeout: str) -> None:
    clean_env.setenv("DB_PING_TIMEOUT_S", timeout)
    with pytest.raises(ValidationError):
        Settings()  # pyright: ignore[reportCallIssue]


@pytest.mark.parametrize(("name", "value"), [("AI_MODE", "sometimes"), ("APP_ENV", "staging")])
def test_unknown_mode_is_refused(clean_env: pytest.MonkeyPatch, name: str, value: str) -> None:
    clean_env.setenv(name, value)
    with pytest.raises(ValidationError):
        Settings()  # pyright: ignore[reportCallIssue]


def test_negative_ai_cap_is_refused(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("AI_MONTHLY_CAP_USD", "-1")
    with pytest.raises(ValidationError):
        Settings()  # pyright: ignore[reportCallIssue]
