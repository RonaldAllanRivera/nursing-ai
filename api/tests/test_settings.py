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
    "APP_ROLE",
    "SITE_URL",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "BOOTSTRAP_ADMIN_EMAIL",
    "IDLE_LOCK_MINUTES",
    "DB_POOL",
    "DB_CONNECT_TIMEOUT_S",
    "DRAFT_QUEUE_URL",
    "AI_DAILY_DRAFTS_PER_USER",
)
CANARY_KEY = "sk-ant-canary-not-a-real-key"
CANARY_GOOGLE_SECRET = "GOCSPX-canary-not-a-real-secret"  # noqa: S105 (a canary, not a secret)
GOOGLE_ID = "1234-canary.apps.googleusercontent.com"
LOCAL_SITE = "http://localhost:5183"


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


def test_missing_database_url_error_never_shows_the_api_key(
    clean_env: pytest.MonkeyPatch,
) -> None:
    short_key = "sk-zz9"  # short, because pydantic shortens long values in its messages
    clean_env.delenv("DATABASE_URL")
    clean_env.setenv("ANTHROPIC_API_KEY", short_key)
    with pytest.raises(ValidationError) as caught:
        Settings()  # pyright: ignore[reportCallIssue]
    assert short_key not in str(caught.value)


def test_defaults_keep_local_dev_unchanged(clean_env: pytest.MonkeyPatch) -> None:
    settings = Settings()  # pyright: ignore[reportCallIssue]
    assert settings.app_role == "api"
    assert settings.site_url is None
    assert settings.google_client_id is None
    assert settings.google_client_secret is None
    assert settings.bootstrap_admin_email is None
    assert settings.idle_lock_minutes == 5
    assert settings.db_pool == "queue"
    assert settings.db_connect_timeout_s == 10.0
    assert settings.draft_queue_url is None
    assert settings.ai_daily_drafts_per_user is None
    assert settings.google_sign_in is False


def test_empty_strings_count_as_unset(clean_env: pytest.MonkeyPatch) -> None:
    # Compose passes `${X:-}`, so a name missing from .env arrives as an empty string.
    for name in (
        "SITE_URL",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "BOOTSTRAP_ADMIN_EMAIL",
        "DRAFT_QUEUE_URL",
        "AI_DAILY_DRAFTS_PER_USER",
    ):
        clean_env.setenv(name, "")
    settings = Settings()  # pyright: ignore[reportCallIssue]
    assert settings.site_url is None
    assert settings.google_client_id is None
    assert settings.google_client_secret is None
    assert settings.bootstrap_admin_email is None
    assert settings.draft_queue_url is None
    assert settings.ai_daily_drafts_per_user is None
    assert settings.google_sign_in is False


def test_google_sign_in_is_on_with_id_secret_and_site_url(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("GOOGLE_CLIENT_ID", GOOGLE_ID)
    clean_env.setenv("GOOGLE_CLIENT_SECRET", CANARY_GOOGLE_SECRET)
    clean_env.setenv("SITE_URL", LOCAL_SITE)
    settings = Settings()  # pyright: ignore[reportCallIssue]
    assert settings.google_sign_in is True


def test_site_url_alone_leaves_google_off(clean_env: pytest.MonkeyPatch) -> None:
    # Compose always passes SITE_URL; the Google client is optional on a developer's PC.
    clean_env.setenv("SITE_URL", LOCAL_SITE)
    settings = Settings()  # pyright: ignore[reportCallIssue]
    assert settings.site_url == LOCAL_SITE
    assert settings.google_sign_in is False


@pytest.mark.parametrize(
    "present",
    [
        ("GOOGLE_CLIENT_ID",),
        ("GOOGLE_CLIENT_SECRET",),
        ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"),
        ("GOOGLE_CLIENT_ID", "SITE_URL"),
        ("GOOGLE_CLIENT_SECRET", "SITE_URL"),
    ],
)
def test_google_needs_id_secret_and_site_url_together(
    clean_env: pytest.MonkeyPatch, present: tuple[str, ...]
) -> None:
    values = {
        "GOOGLE_CLIENT_ID": GOOGLE_ID,
        "GOOGLE_CLIENT_SECRET": CANARY_GOOGLE_SECRET,
        "SITE_URL": LOCAL_SITE,
    }
    for name in present:
        clean_env.setenv(name, values[name])
    with pytest.raises(ValueError, match="GOOGLE_CLIENT_ID") as caught:
        Settings()  # pyright: ignore[reportCallIssue]
    assert CANARY_GOOGLE_SECRET not in str(caught.value)


@pytest.mark.parametrize(
    "url", ["http://localhost:5183", "http://127.0.0.1:8010", "https://demo.example.com"]
)
def test_site_url_is_an_origin(clean_env: pytest.MonkeyPatch, url: str) -> None:
    clean_env.setenv("SITE_URL", url)
    assert Settings().site_url == url  # pyright: ignore[reportCallIssue]


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:5183/",
        "http://localhost:5183/app",
        "https://demo.example.com?next=1",
        "https://demo.example.com#top",
        "https://user:pw@demo.example.com",
        "ftp://demo.example.com",
        "localhost:5183",
        "https://",
    ],
)
def test_site_url_that_is_not_an_origin_is_refused(clean_env: pytest.MonkeyPatch, url: str) -> None:
    clean_env.setenv("SITE_URL", url)
    with pytest.raises(ValidationError, match="SITE_URL"):
        Settings()  # pyright: ignore[reportCallIssue]


def test_bootstrap_admin_email_is_lowercased(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("BOOTSTRAP_ADMIN_EMAIL", "  Ward.Admin@Example.COM ")
    settings = Settings()  # pyright: ignore[reportCallIssue]
    assert settings.bootstrap_admin_email == "ward.admin@example.com"


@pytest.mark.parametrize("email", ["nobody", "a@b@example.com", "@example.com", "admin@"])
def test_bootstrap_admin_email_needs_exactly_one_at(
    clean_env: pytest.MonkeyPatch, email: str
) -> None:
    clean_env.setenv("BOOTSTRAP_ADMIN_EMAIL", email)
    with pytest.raises(ValidationError, match="BOOTSTRAP_ADMIN_EMAIL"):
        Settings()  # pyright: ignore[reportCallIssue]


def test_lambda_settings_come_from_the_environment(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("APP_ROLE", "worker")
    clean_env.setenv("IDLE_LOCK_MINUTES", "7")
    clean_env.setenv("DB_POOL", "null")
    clean_env.setenv("DB_CONNECT_TIMEOUT_S", "20")
    clean_env.setenv("DRAFT_QUEUE_URL", "https://sqs.example.com/000000000000/jobs")
    clean_env.setenv("AI_DAILY_DRAFTS_PER_USER", "20")
    settings = Settings()  # pyright: ignore[reportCallIssue]
    assert settings.app_role == "worker"
    assert settings.idle_lock_minutes == 7
    assert settings.db_pool == "null"
    assert settings.db_connect_timeout_s == 20.0
    assert settings.draft_queue_url == "https://sqs.example.com/000000000000/jobs"
    assert settings.ai_daily_drafts_per_user == 20


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("APP_ROLE", "batch"),
        ("DB_POOL", "static"),
        ("IDLE_LOCK_MINUTES", "0"),
        ("IDLE_LOCK_MINUTES", "31"),
        ("DB_CONNECT_TIMEOUT_S", "0"),
        ("AI_DAILY_DRAFTS_PER_USER", "0"),
    ],
)
def test_out_of_range_p2_settings_are_refused(
    clean_env: pytest.MonkeyPatch, name: str, value: str
) -> None:
    clean_env.setenv(name, value)
    with pytest.raises(ValidationError):
        Settings()  # pyright: ignore[reportCallIssue]


def test_google_secret_never_in_repr(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("GOOGLE_CLIENT_ID", GOOGLE_ID)
    clean_env.setenv("GOOGLE_CLIENT_SECRET", CANARY_GOOGLE_SECRET)
    clean_env.setenv("SITE_URL", LOCAL_SITE)
    settings = Settings()  # pyright: ignore[reportCallIssue]
    assert settings.google_client_secret is not None
    assert settings.google_client_secret.get_secret_value() == CANARY_GOOGLE_SECRET
    assert CANARY_GOOGLE_SECRET not in repr(settings)
    assert CANARY_GOOGLE_SECRET not in str(settings.model_dump())
