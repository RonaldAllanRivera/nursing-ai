"""Which AI provider drafts a note: by `AI_MODE`, with the budget guard around the live one."""

from collections.abc import Callable

from nursing_core.demo import load_demo_cases
from nursing_core.domain.errors import ReplayMissing
from nursing_core.domain.patient import PatientRecord
from nursing_core.ports import Clock, LlmProvider
from nursing_core.providers.anthropic import AnthropicProvider
from nursing_core.providers.fake import FakeProvider
from nursing_core.providers.replay import RECORDINGS_DIR, ReplayProvider
from nursing_core.storage.repositories import PgUsageRepository

from nursing_api.budget import BudgetGuard
from nursing_api.settings import Settings

ProviderFor = Callable[[PatientRecord], LlmProvider]

LIVE_MODEL = "claude-opus-5-5"
LIVE_NEEDS = "AI_MODE=live needs AI_MONTHLY_CAP_USD and ANTHROPIC_API_KEY"


def check_live_settings(settings: Settings) -> None:
    """Live mode needs a monthly cap and a key; ValueError otherwise (the app won't start)."""
    if settings.ai_mode == "live" and (
        settings.ai_monthly_cap_usd is None or settings.anthropic_api_key is None
    ):
        raise ValueError(LIVE_NEEDS)


def _the_same(provider: LlmProvider) -> ProviderFor:
    return lambda _patient: provider


def _mock_provider_for() -> ProviderFor:
    """The canned draft of the demo case that owns the patient; any other patient has none."""
    outputs = {case.patient_id: case.model_output for case in load_demo_cases()}

    def provider_for(patient: PatientRecord) -> LlmProvider:
        output = outputs.get(patient.summary.id)
        if output is None:
            raise ReplayMissing("no canned draft for this patient")
        return FakeProvider(output, identity=patient.identity)

    return provider_for


def provider_factory(
    settings: Settings,
    usage: PgUsageRepository,
    clock: Clock,
    override: ProviderFor | None = None,
) -> ProviderFor:
    """The provider for a patient's note.

    `override` replaces the inner provider (tests use it so nothing reaches the network). In live
    mode the budget guard goes around the inner provider, whatever it is.
    """
    check_live_settings(settings)
    if override is not None:
        inner = override
    elif settings.ai_mode == "mock":
        inner = _mock_provider_for()
    elif settings.ai_mode == "replay":
        inner = _the_same(ReplayProvider(RECORDINGS_DIR))
    else:
        key = settings.anthropic_api_key
        if key is None:
            raise ValueError(LIVE_NEEDS)
        inner = _the_same(AnthropicProvider(key, model=LIVE_MODEL))
    if settings.ai_mode != "live":
        return inner
    # Live always gets the guard: a missing cap stops here, it never means "no limit".
    cap = settings.ai_monthly_cap_usd
    if cap is None:
        raise ValueError(LIVE_NEEDS)
    return lambda patient: BudgetGuard(inner(patient), usage, clock, cap, LIVE_MODEL)
