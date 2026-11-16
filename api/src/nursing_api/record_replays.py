"""`python -m nursing_api.record_replays`: records the demo drafts from the live model, once.

This is the only code that spends money on purpose. It asks the model once for each demo note
(none that already replays, unless `--force`), stops at the first failure and never retries.
Each note goes through the real draft pipeline, so the request is the one the worker sends, and
the answer is saved where replay mode looks for it.

It prints the case key, what happened, the file name's first 12 characters and the cost. Never a
note, a draft, a name, the API key, or an exception's text (a driver or SDK message can carry the
URL or a header): an error is shown as its class name only.
"""

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

from nursing_core.clock import SystemClock
from nursing_core.db import create_engine
from nursing_core.demo import load_demo_cases
from nursing_core.domain.errors import NotFound, ReplayMissing
from nursing_core.domain.model_output import DraftRequest, ProviderResult
from nursing_core.domain.patient import PatientRecord
from nursing_core.pipeline.fdar import run_fdar_pipeline
from nursing_core.ports import LlmProvider
from nursing_core.providers.replay import (
    RECORDINGS_DIR,
    ReplayProvider,
    replay_key,
    save_recording,
)
from nursing_core.storage.repositories import PgPatientRepository, PgUsageRepository
from pydantic import ValidationError

from .providers import LIVE_MODEL, ProviderFor, provider_factory
from .settings import Settings
from .usage import UsageRecorder

NOT_LIVE = "Not recording: AI_MODE must be live (run `make record-replays AI_MODE=live`)."
NO_KEY = "Not recording: ANTHROPIC_API_KEY is not set (put it in .env)."
NO_CAP = "Not recording: AI_MONTHLY_CAP_USD is not set."
NO_URL = "Not recording: DATABASE_URL is not set. Run `make up`, then try again."
UNSEEDED = "Not recording: the demo patients are not in the database. Run `make seed`."
INVALID = "Settings are invalid: check AI_MODE, AI_MONTHLY_CAP_USD and DB_PING_TIMEOUT_S."


class _Step:
    """The provider for one demo note: replays a recording if there is one, else asks the model.

    It keeps what the pipeline sent and what came back, so the caller can save it once the
    pipeline has accepted the answer.
    """

    def __init__(self, live: LlmProvider, out_dir: Path, force: bool) -> None:
        self._live = live
        self._out_dir = out_dir
        self._force = force
        self.request: DraftRequest | None = None
        self.answer: ProviderResult | None = None
        self.skipped = False

    async def draft_fdar(self, request: DraftRequest) -> ProviderResult:
        self.request = request
        if not self._force:
            try:
                replayed = await ReplayProvider(self._out_dir, LIVE_MODEL).draft_fdar(request)
            except ReplayMissing:
                pass
            else:
                self.skipped = True
                return replayed
        self.answer = await self._live.draft_fdar(request)
        return self.answer


def _money(amount: Decimal) -> str:
    return f"${amount:.6f}"


async def _record(
    settings: Settings, provider_for: ProviderFor | None, out_dir: Path, force: bool
) -> int:
    engine = create_engine(settings.database_url)
    try:
        clock = SystemClock()
        patients = PgPatientRepository(engine, clock)
        usage = PgUsageRepository(engine)
        cases = load_demo_cases()
        try:
            records: list[PatientRecord] = [
                await patients.get_patient(case.patient_id) for case in cases
            ]
        except NotFound:
            print(UNSEEDED)
            return 1
        make_provider = provider_factory(settings, usage, clock, provider_for)
        total, calls, code = Decimal(0), 0, 0
        for case, patient in zip(cases, records, strict=True):
            step = _Step(UsageRecorder(make_provider(patient), usage, clock, None), out_dir, force)
            try:
                await run_fdar_pipeline(case.rough_note, patient, [], step)
                if step.skipped:
                    name = _name(step.request)
                    print(f"{case.key}: skipped (already recorded) {name} {_money(Decimal(0))}")
                    continue
                request, answer = step.request, step.answer
                if request is None or answer is None:
                    raise RuntimeError  # the pipeline always asks once; never saved blind
                save_recording(request, answer, out_dir, LIVE_MODEL)
                await ReplayProvider(out_dir, LIVE_MODEL).draft_fdar(request)  # a miss raises
            except Exception as error:
                print(f"{case.key}: failed ({type(error).__name__})")
                code = 1
                break
            cost = answer.generation.cost_usd
            total, calls = total + cost, calls + 1
            print(f"{case.key}: recorded {_name(request)} {_money(cost)}")
        noun = "call" if calls == 1 else "calls"
        print(f"total: {_money(total)} over {calls} {noun}")
        return code
    finally:
        await engine.dispose()


def _name(request: DraftRequest | None) -> str:
    return "" if request is None else replay_key(request, LIVE_MODEL)[:12]


def main(argv: Sequence[str] | None = None, *, provider_for: ProviderFor | None = None) -> int:
    """Record the demo drafts. `provider_for` replaces the live provider (tests only)."""
    parser = argparse.ArgumentParser(prog="record_replays", description=__doc__)
    parser.add_argument("--out", type=Path, default=RECORDINGS_DIR)
    parser.add_argument("--force", action="store_true", help="record all three again")
    args = parser.parse_args(argv)
    try:
        settings = Settings(database_url=os.environ.get("DATABASE_URL", ""))
    except ValidationError:
        # Never the error itself: pydantic echoes the offending value.
        print(INVALID)
        return 1
    key = settings.anthropic_api_key
    for refused, line in (
        (settings.ai_mode != "live", NOT_LIVE),
        (key is None or not key.get_secret_value(), NO_KEY),
        (settings.ai_monthly_cap_usd is None, NO_CAP),
        (not settings.database_url, NO_URL),
    ):
        if refused:
            print(line)
            return 1
    return asyncio.run(_record(settings, provider_for, args.out, args.force))


if __name__ == "__main__":
    sys.exit(main())
