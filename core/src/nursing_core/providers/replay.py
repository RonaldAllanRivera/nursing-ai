"""Replay of recorded model output, so the demo and end-to-end tests show real drafts at no cost.

A recording is one JSON file named by the SHA-256 of the request and the model's name. It holds
the request and the provider's result, so a replay can check it is answering the same request.
"""

import asyncio
import hashlib
import json
from decimal import Decimal
from pathlib import Path

from nursing_core.domain.errors import ReplayMissing
from nursing_core.domain.model_output import DraftRequest, ProviderResult
from nursing_core.ports import LlmProvider

RECORDINGS_DIR = Path(__file__).parent / "recordings"


def replay_key(request: DraftRequest, model: str) -> str:
    payload = {"request": request.model_dump(mode="json"), "model": model}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


class ReplayProvider:
    def __init__(self, recordings: Path, model: str = "claude-opus-5-5") -> None:
        self.recordings = recordings
        self.model = model

    async def draft_fdar(self, request: DraftRequest) -> ProviderResult:
        path = self.recordings / f"{replay_key(request, self.model)}.json"
        if not path.is_file():
            raise ReplayMissing("no recording matches this request")
        stored = json.loads(path.read_text(encoding="utf-8"))
        if stored["request"] != request.model_dump(mode="json"):
            raise ReplayMissing("the recording belongs to a different request")
        recorded = ProviderResult.model_validate(stored["result"])
        generation = recorded.generation.model_copy(
            update={"provider": "replay", "cost_usd": Decimal(0), "latency_ms": 0}
        )
        return ProviderResult(output=recorded.output, generation=generation)


async def record(request: DraftRequest, provider: LlmProvider, out_dir: Path) -> Path:
    """Asks the provider once and saves its answer, keyed by the model that gave it."""
    result = await provider.draft_fdar(request)
    path = out_dir / f"{replay_key(request, result.generation.model)}.json"
    document = {
        "request": request.model_dump(mode="json"),
        "result": result.model_dump(mode="json"),
    }
    text = json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    await asyncio.to_thread(_write, path, text)
    return path


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
