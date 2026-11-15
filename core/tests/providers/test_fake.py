"""The fake provider: fixed output for tests and the demo, and the privacy canary."""

from decimal import Decimal

import pytest
from nursing_core.demo import load_demo_cases
from nursing_core.domain.errors import PhiLeak
from nursing_core.domain.facility import Locale, NoteFormat
from nursing_core.domain.model_output import (
    DraftRequest,
    ModelFdarDraft,
    ModelFdarEntry,
    ModelLine,
)
from nursing_core.pipeline.redact import redact
from nursing_core.ports import LlmProvider
from nursing_core.providers.fake import FakeProvider

PERPETUA = load_demo_cases()[0].patient

OUTPUT = ModelFdarDraft(
    entries=[
        ModelFdarEntry(
            focus=ModelLine(text="Pain", source_quotes=[], own_wording=True),
            data=[ModelLine(text="Pain 6/10", source_quotes=["pain 6/10"], own_wording=False)],
            action=[],
            response=[],
        )
    ]
)


def _request(text: str) -> DraftRequest:
    return DraftRequest(
        redacted_text=text,
        note_format=NoteFormat.FDAR,
        locale=Locale.EN_US,
        prompt_version="fdar-v1",
    )


def test_fake_provider_is_an_llm_provider() -> None:
    provider: LlmProvider = FakeProvider(OUTPUT)
    assert provider is not None


@pytest.mark.asyncio
async def test_fake_provider_returns_its_output() -> None:
    result = await FakeProvider(OUTPUT).draft_fdar(_request("pain 6/10"))
    assert result.output == OUTPUT
    assert result.generation.provider == "fake"
    assert result.generation.model == "fake"
    assert result.generation.prompt_version == "fdar-v1"
    assert (result.generation.input_tokens, result.generation.output_tokens) == (0, 0)
    assert result.generation.cost_usd == Decimal(0)
    assert result.generation.latency_ms == 0


@pytest.mark.asyncio
async def test_fake_provider_refuses_a_known_name() -> None:
    provider = FakeProvider(OUTPUT, identity=PERPETUA)
    with pytest.raises(PhiLeak) as caught:
        await provider.draft_fdar(_request("Perpetua Malabanan has pain 6/10"))
    assert "Perpetua" not in str(caught.value)
    assert "Malabanan" not in str(caught.value)


@pytest.mark.asyncio
async def test_fake_provider_accepts_a_redacted_note() -> None:
    note = redact("Perpetua Malabanan has pain 6/10", PERPETUA).text
    result = await FakeProvider(OUTPUT, identity=PERPETUA).draft_fdar(_request(note))
    assert result.output == OUTPUT
