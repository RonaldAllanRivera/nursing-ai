"""The budget guard's worst-case estimate: note, prompt and output schema, plus max output."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast

import pytest
from nursing_api import budget
from nursing_api.budget import BudgetGuard
from nursing_core.clock import FixedClock
from nursing_core.demo import load_demo_cases
from nursing_core.domain.errors import AiBudgetReached
from nursing_core.domain.facility import Locale, NoteFormat
from nursing_core.domain.model_output import DraftRequest
from nursing_core.prompts import FDAR_PROMPT_VERSION, load_prompt
from nursing_core.providers import anthropic as provider
from nursing_core.providers.fake import FakeProvider
from nursing_core.providers.pricing import cost_usd
from nursing_core.storage.repositories import PgUsageRepository

MODEL = "claude-opus-5-5"
NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)


class _NothingSpent:
    async def month_total(self, _now: datetime) -> tuple[Decimal, int]:
        return Decimal(0), 0


def _request() -> DraftRequest:
    return DraftRequest(
        redacted_text="Zorblat note text",
        note_format=next(iter(NoteFormat)),
        locale=Locale.EN_US,
        prompt_version=FDAR_PROMPT_VERSION,
    )


def _guard(cap: Decimal) -> BudgetGuard:
    usage = cast(PgUsageRepository, _NothingSpent())
    return BudgetGuard(
        FakeProvider(load_demo_cases()[0].model_output), usage, FixedClock(NOW), cap, MODEL
    )


def _estimate(schema_chars: int) -> Decimal:
    request = _request()
    chars = len(load_prompt(request.prompt_version)) + len(request.redacted_text) + schema_chars
    return cost_usd(MODEL, chars, provider.MAX_OUTPUT_TOKENS)


async def _passes(cap: Decimal) -> bool:
    try:
        await _guard(cap).draft_fdar(_request())
    except AiBudgetReached:
        return False
    return True


@pytest.mark.asyncio
async def test_the_estimate_counts_the_schema_the_provider_sends() -> None:
    chars = len(json.dumps(provider.output_schema()))
    assert chars > 0
    exact = _estimate(chars)
    assert await _passes(exact)
    assert not await _passes(exact - Decimal("0.000001"))


@pytest.mark.asyncio
async def test_the_estimate_grows_with_the_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    exact = _estimate(budget.SCHEMA_CHARS)
    monkeypatch.setattr(budget, "SCHEMA_CHARS", budget.SCHEMA_CHARS + 1_000_000)
    assert not await _passes(exact)


def test_the_output_ceiling_is_the_providers_own() -> None:
    assert vars(budget)["MAX_OUTPUT_TOKENS"] == provider.MAX_OUTPUT_TOKENS
    assert provider.MAX_OUTPUT_TOKENS == 16000
