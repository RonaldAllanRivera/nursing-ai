"""The monthly AI spend cap: checked before every live call. Concurrent calls can still pass it."""

from decimal import Decimal

from nursing_core.domain.errors import AiBudgetReached
from nursing_core.domain.model_output import DraftRequest, ProviderResult
from nursing_core.ports import Clock, LlmProvider
from nursing_core.prompts import load_prompt
from nursing_core.providers.pricing import cost_usd
from nursing_core.storage.repositories import PgUsageRepository

# The provider's own ceiling on one answer (`max_tokens`).
MAX_OUTPUT_TOKENS = 16000


class BudgetGuard:
    """Wraps a provider: a call that could take the month past the cap never starts.

    The estimate is the worst case of one call: one token per character of the system prompt and
    the redacted note (never fewer tokens than that), plus the largest answer the provider allows.
    Two calls checked at the same moment can both pass; the cap is a safety net, not a ledger.
    """

    def __init__(
        self,
        inner: LlmProvider,
        usage: PgUsageRepository,
        clock: Clock,
        cap_usd: Decimal,
        model: str,
    ) -> None:
        self._inner = inner
        self._usage = usage
        self._clock = clock
        self._cap = cap_usd
        self._model = model

    async def draft_fdar(self, request: DraftRequest) -> ProviderResult:
        spent, _calls = await self._usage.month_total(self._clock.now())
        input_chars = len(load_prompt(request.prompt_version)) + len(request.redacted_text)
        worst_case = cost_usd(self._model, input_chars, MAX_OUTPUT_TOKENS)
        if spent + worst_case > self._cap:
            raise AiBudgetReached("the monthly AI cap would be passed")
        return await self._inner.draft_fdar(request)
