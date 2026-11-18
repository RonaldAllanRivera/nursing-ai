"""Counting what the AI costs: one `ai_usage` row for every answer a provider gives."""

from decimal import Decimal
from uuid import UUID

from nursing_core.domain.errors import BilledError
from nursing_core.domain.model_output import DraftRequest, ProviderResult
from nursing_core.ports import Clock, LlmProvider
from nursing_core.storage.repositories import PgUsageRepository


class UsageRecorder:
    """Wraps a provider: one `ai_usage` row for every answer the provider gives, or fails after.

    The row is written as soon as the provider returns, so a billed answer that the pipeline then
    refuses (an empty draft) is still counted against the cap. `job_id` is None for a call that
    belongs to no draft job.
    """

    def __init__(
        self, inner: LlmProvider, usage: PgUsageRepository, clock: Clock, job_id: UUID | None
    ) -> None:
        self._inner = inner
        self._usage = usage
        self._clock = clock
        self._job_id = job_id
        self.cost_usd = Decimal(0)  # what this recorder has recorded, for the spend metric

    async def draft_fdar(self, request: DraftRequest) -> ProviderResult:
        try:
            result = await self._inner.draft_fdar(request)
        except BilledError as error:
            # A billed answer that failed inside the provider still counts; the error goes on.
            if error.generation is not None:
                await self._usage.record(self._job_id, error.generation, self._clock.now())
                self.cost_usd += error.generation.cost_usd
            raise
        await self._usage.record(self._job_id, result.generation, self._clock.now())
        self.cost_usd += result.generation.cost_usd
        return result
