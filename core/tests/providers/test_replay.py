"""Replay: recorded model output comes back at no cost, and a missing recording is an error."""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from nursing_core.domain.errors import ReplayMissing
from nursing_core.domain.facility import Locale, NoteFormat
from nursing_core.domain.model_output import (
    DraftRequest,
    ModelFdarDraft,
    ModelFdarEntry,
    ModelLine,
    ProviderResult,
)
from nursing_core.domain.notes import GenerationInfo
from nursing_core.ports import LlmProvider
from nursing_core.providers.fake import FakeProvider
from nursing_core.providers.replay import RECORDINGS_DIR, ReplayProvider, record, replay_key

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


def _request(text: str = "pain 6/10", locale: Locale = Locale.EN_US) -> DraftRequest:
    return DraftRequest(
        redacted_text=text,
        note_format=NoteFormat.FDAR,
        locale=locale,
        prompt_version="fdar-v1",
    )


class _Recorded:
    """Answers like a live provider, with a model name and token counts to record."""

    async def draft_fdar(self, request: DraftRequest) -> ProviderResult:
        return ProviderResult(
            output=OUTPUT,
            generation=GenerationInfo(
                provider="anthropic",
                model="claude-opus-5-5",
                prompt_version=request.prompt_version,
                input_tokens=900,
                output_tokens=120,
                cost_usd=Decimal("0.006"),
                latency_ms=4200,
            ),
        )


def test_replay_key_is_stable_and_depends_on_request_and_model() -> None:
    key = replay_key(_request(), "claude-opus-5-5")
    assert key == replay_key(_request(), "claude-opus-5-5")
    assert len(key) == 64
    assert key != replay_key(_request("other note"), "claude-opus-5-5")
    assert key != replay_key(_request(locale=Locale.EN_PH), "claude-opus-5-5")
    assert key != replay_key(_request(), "another-model")


def test_recordings_dir_is_the_packages_folder() -> None:
    assert RECORDINGS_DIR.name == "recordings"
    assert (RECORDINGS_DIR / "README.md").is_file()


@pytest.mark.asyncio
async def test_record_writes_a_file_named_by_its_key(tmp_path: Path) -> None:
    out_dir = tmp_path / "new" / "folder"
    path = await record(_request(), _Recorded(), out_dir)
    assert path == out_dir / f"{replay_key(_request(), 'claude-opus-5-5')}.json"
    text = path.read_text(encoding="utf-8")
    assert text.endswith("}\n")
    assert json.loads(text)["request"]["redacted_text"] == "pain 6/10"
    assert '\n  "request"' in text


@pytest.mark.asyncio
async def test_replay_returns_recording(tmp_path: Path) -> None:
    await record(_request(), _Recorded(), tmp_path)
    provider: LlmProvider = ReplayProvider(tmp_path)
    result = await provider.draft_fdar(_request())
    assert result.output == OUTPUT
    generation = result.generation
    assert generation.provider == "replay"
    assert generation.model == "claude-opus-5-5"
    assert generation.prompt_version == "fdar-v1"
    assert (generation.input_tokens, generation.output_tokens) == (900, 120)
    assert generation.cost_usd == Decimal(0)
    assert generation.latency_ms == 0


@pytest.mark.asyncio
async def test_replay_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(ReplayMissing) as caught:
        await ReplayProvider(tmp_path).draft_fdar(_request("a note nobody recorded"))
    assert "nobody recorded" not in str(caught.value)


@pytest.mark.asyncio
async def test_replay_of_a_recording_for_another_request_raises(tmp_path: Path) -> None:
    path = await record(_request(), _Recorded(), tmp_path)
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["request"]["redacted_text"] = "something else"
    path.write_text(json.dumps(stored), encoding="utf-8")
    with pytest.raises(ReplayMissing):
        await ReplayProvider(tmp_path).draft_fdar(_request())


@pytest.mark.asyncio
async def test_record_keys_by_the_models_name(tmp_path: Path) -> None:
    path = await record(_request(), FakeProvider(OUTPUT), tmp_path)
    assert path.name == f"{replay_key(_request(), 'fake')}.json"
    assert await ReplayProvider(tmp_path, model="fake").draft_fdar(_request())
