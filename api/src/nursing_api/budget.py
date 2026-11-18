"""The monthly AI spend cap: a live call first holds its worst case against it."""

import json
from decimal import Decimal
from uuid import UUID

from nursing_core.domain.model_output import DraftRequest, ProviderResult
from nursing_core.ports import Clock, LlmProvider
from nursing_core.prompts import load_prompt
from nursing_core.providers.anthropic import MAX_OUTPUT_TOKENS, output_schema
from nursing_core.providers.pricing import cost_usd
from nursing_core.storage.repositories import PgUsageRepository

# The schema is sent with every request, so it counts as input (the same one-token-per-character).
SCHEMA_CHARS = len(json.dumps(output_schema()))


class BudgetGuard:
    """Wraps a provider: a call that could take the month past the cap never starts.

    The estimate is the worst case of one call: one token per character of the system prompt, the
    redacted note and the output schema (never fewer tokens than that), plus the largest answer
    the provider allows.
    The worst case is held against the cap under a lock (see `PgUsageRepository.hold`), so two
    calls at the same moment can't both pass it. Recording the call's usage releases the hold.
    """

    def __init__(
        self,
        inner: LlmProvider,
        usage: PgUsageRepository,
        clock: Clock,
        cap_usd: Decimal,
        model: str,
        job_id: UUID | None = None,
    ) -> None:
        self._inner = inner
        self._usage = usage
        self._clock = clock
        self._cap = cap_usd
        self._model = model
        self._job_id = job_id

    async def draft_fdar(self, request: DraftRequest) -> ProviderResult:
        input_chars = (
            len(load_prompt(request.prompt_version)) + len(request.redacted_text) + SCHEMA_CHARS
        )
        worst_case = cost_usd(self._model, input_chars, MAX_OUTPUT_TOKENS)
        await self._usage.hold(self._job_id, worst_case, self._cap, self._clock.now())
        return await self._inner.draft_fdar(request)
