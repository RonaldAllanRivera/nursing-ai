"""The live Anthropic client is built to give up before the worker Lambda is killed."""

from typing import Any
from unittest.mock import MagicMock

import pytest
from nursing_api import providers
from nursing_api.providers import provider_factory
from nursing_api.settings import Settings

from .helpers import MutableClock


def test_the_live_client_times_out_below_the_workers_120_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built = MagicMock()
    monkeypatch.setattr(providers, "AnthropicProvider", built)
    settings = Settings.model_validate(
        {
            "database_url": "postgresql+asyncpg://u:p@localhost/db",
            "app_env": "test",
            "ai_mode": "live",
            "ai_monthly_cap_usd": "5",
            "anthropic_api_key": "sk-test-not-a-key",
        }
    )

    provider_factory(settings, MagicMock(), MutableClock())

    kwargs: Any = built.call_args.kwargs
    assert kwargs["timeout"] == 80
