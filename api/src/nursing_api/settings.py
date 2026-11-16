from decimal import Decimal
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Reads environment variables only, never a .env file.

    Locally, Compose and the Makefile pass the values in; in AWS, the Lambda environment does.
    """

    model_config = SettingsConfigDict(env_file=None, hide_input_in_errors=True)

    app_env: Literal["dev", "test", "demo", "prod"] = "dev"
    database_url: str
    db_ping_timeout_s: float = Field(default=2.0, gt=0)
    ai_mode: Literal["mock", "replay", "live"] = "mock"
    ai_monthly_cap_usd: Decimal | None = Field(default=None, ge=0)
    anthropic_api_key: SecretStr | None = None
