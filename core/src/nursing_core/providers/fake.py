"""A provider that returns a fixed draft. It is also the privacy canary: it refuses any request
that still holds an identity string of the patient."""

from decimal import Decimal

from nursing_core.domain.errors import PhiLeak
from nursing_core.domain.model_output import DraftRequest, ModelFdarDraft, ProviderResult
from nursing_core.domain.notes import GenerationInfo
from nursing_core.domain.patient import PatientIdentity
from nursing_core.pipeline.redact import mentions_identity


class FakeProvider:
    def __init__(self, output: ModelFdarDraft, identity: PatientIdentity | None = None) -> None:
        self.output = output
        self.identity = identity

    async def draft_fdar(self, request: DraftRequest) -> ProviderResult:
        if self.identity is not None and mentions_identity(request.redacted_text, self.identity):
            raise PhiLeak("a known identifier reached the provider")
        return ProviderResult(
            output=self.output,
            generation=GenerationInfo(
                provider="fake",
                model="fake",
                prompt_version=request.prompt_version,
                input_tokens=0,
                output_tokens=0,
                cost_usd=Decimal(0),
                latency_ms=0,
            ),
        )
