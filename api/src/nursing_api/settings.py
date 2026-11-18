from decimal import Decimal
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Reads environment variables only, never a .env file.

    Locally, Compose and the Makefile pass the values in; in AWS, the Lambda environment does.
    An empty value counts as unset, because Compose passes `${X:-}` for a name .env leaves out.
    """

    model_config = SettingsConfigDict(
        env_file=None, hide_input_in_errors=True, env_ignore_empty=True
    )

    app_env: Literal["dev", "test", "demo", "prod"] = "dev"
    app_role: Literal["api", "worker", "ops"] = "api"
    # The URL carries the database password (live, from SSM), so it stays out of repr and str.
    database_url: str = Field(repr=False)
    db_ping_timeout_s: float = Field(default=2.0, gt=0)
    db_pool: Literal["queue", "null"] = "queue"
    db_connect_timeout_s: float = Field(default=10.0, gt=0)
    ai_mode: Literal["mock", "replay", "live"] = "mock"
    ai_monthly_cap_usd: Decimal | None = Field(default=None, ge=0)
    ai_daily_drafts_per_user: int | None = Field(default=None, ge=1)
    anthropic_api_key: SecretStr | None = None
    # Every absolute URL the app writes (Google's redirect, for one) starts here, never at the
    # request's Host header.
    site_url: str | None = None
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    bootstrap_admin_email: str | None = Field(default=None, repr=False)
    idle_lock_minutes: int = Field(default=5, ge=1, le=30)
    draft_queue_url: str | None = None

    @field_validator("site_url")
    @classmethod
    def _site_url_is_an_origin(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parts = urlsplit(value)
        try:
            parts.port  # noqa: B018  # raises for a port that isn't a number from 0 to 65535
        except ValueError:
            raise ValueError("SITE_URL has a port that isn't a number") from None
        if (
            parts.scheme not in ("http", "https")
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or value != f"{parts.scheme}://{parts.netloc}"
        ):
            raise ValueError(
                "SITE_URL must be an http(s) origin with no path or trailing slash, "
                "such as http://localhost:5183"
            )
        return value

    @field_validator("bootstrap_admin_email")
    @classmethod
    def _bootstrap_admin_email_is_lowercase(cls, value: str | None) -> str | None:
        if value is None:
            return None
        email = value.strip().lower()
        local, _, domain = email.partition("@")
        if email.count("@") != 1 or not local or not domain:
            raise ValueError("BOOTSTRAP_ADMIN_EMAIL must be one email address")
        return email

    @model_validator(mode="after")
    def _google_needs_every_part(self) -> Self:
        parts = (self.google_client_id, self.google_client_secret, self.site_url)
        if (self.google_client_id or self.google_client_secret) and None in parts:
            raise ValueError(
                "Google sign-in needs GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and SITE_URL together"
            )
        return self

    @property
    def google_sign_in(self) -> bool:
        """True when the Google client and the site's address are all set."""
        return None not in (self.google_client_id, self.google_client_secret, self.site_url)
