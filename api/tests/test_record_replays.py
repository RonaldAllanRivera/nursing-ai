"""`python -m nursing_api.record_replays`: records the demo drafts, with a fake model (cost: $0)."""

import asyncio
import json
from decimal import Decimal
from pathlib import Path

import pytest
from nursing_api.providers import LIVE_MODEL
from nursing_api.record_replays import main
from nursing_core.clock import SystemClock
from nursing_core.db import create_engine
from nursing_core.demo import load_demo_cases
from nursing_core.domain.errors import ProviderUnavailable
from nursing_core.domain.model_output import DraftRequest, ModelFdarDraft, ProviderResult
from nursing_core.domain.notes import GenerationInfo
from nursing_core.domain.patient import PatientRecord
from nursing_core.ports import LlmProvider
from nursing_core.providers.fake import FakeProvider
from nursing_core.providers.replay import ReplayProvider, replay_key
from nursing_core.storage.repositories import PgUsageRepository
from sqlalchemy import text

from .helpers import (
    STAFF_NURSE,
    MutableClock,
    client_for,
    forbidden_words,
    post_note,
    running_app,
    sign_in,
)

CASES = load_demo_cases()
KEY = "sk-ant-canary-not-a-real-key"
ANSWERED_AS = "claude-opus-5-5-20261101"
SETTING_NAMES = ("APP_ENV", "DATABASE_URL", "AI_MODE", "AI_MONTHLY_CAP_USD", "ANTHROPIC_API_KEY")


class Fakes:
    """The demo cases' canned drafts, answering as a longer model snapshot at $0.50 a call.

    It is the `provider_for` the module is given; `requests` is every request it was asked.
    `fail_on_call` makes that call (1-based) fail.
    """

    def __init__(self, fail_on_call: int | None = None, empty_draft: bool = False) -> None:
        self.requests: list[DraftRequest] = []
        self.fail_on_call = fail_on_call
        self.empty_draft = empty_draft  # a billed answer the pipeline refuses

    def __call__(self, patient: PatientRecord) -> LlmProvider:
        case = next(c for c in CASES if c.patient_id == patient.summary.id)
        return _Counting(self, FakeProvider(case.model_output, identity=patient.identity))


class _Counting:
    def __init__(self, fakes: Fakes, inner: FakeProvider) -> None:
        self._fakes = fakes
        self._inner = inner

    async def draft_fdar(self, request: DraftRequest) -> ProviderResult:
        self._fakes.requests.append(request)
        if self._fakes.fail_on_call == len(self._fakes.requests):
            raise ProviderUnavailable("boom")
        result = await self._inner.draft_fdar(request)
        generation = result.generation.model_copy(
            update={"model": ANSWERED_AS, "cost_usd": Decimal("0.5")}
        )
        output = ModelFdarDraft(entries=[]) if self._fakes.empty_draft else result.output
        return ProviderResult(output=output, generation=generation)


def _files(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir())


@pytest.fixture(autouse=True)
def live_env(monkeypatch: pytest.MonkeyPatch, database_url: str) -> None:
    for name in SETTING_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("AI_MODE", "live")
    monkeypatch.setenv("AI_MONTHLY_CAP_USD", "20")
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)


async def run(tmp_path: Path, fakes: Fakes, *args: str) -> int:
    return await asyncio.to_thread(main, ["--out", str(tmp_path), *args], provider_for=fakes)


def _out(capsys: pytest.CaptureFixture[str]) -> tuple[list[str], str]:
    captured = capsys.readouterr()
    assert KEY not in captured.out + captured.err
    return captured.out.splitlines(), captured.err


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("missing", "line"),
    [
        (
            "AI_MODE",
            "Not recording: AI_MODE must be live (run `make record-replays AI_MODE=live`).",
        ),
        ("ANTHROPIC_API_KEY", "Not recording: ANTHROPIC_API_KEY is not set (put it in .env)."),
        ("AI_MONTHLY_CAP_USD", "Not recording: AI_MONTHLY_CAP_USD is not set."),
        ("DATABASE_URL", "Not recording: DATABASE_URL is not set. Run `make up`, then try again."),
    ],
)
async def test_refuses_without_what_it_needs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    missing: str,
    line: str,
) -> None:
    if missing == "AI_MODE":
        monkeypatch.setenv("AI_MODE", "replay")
    else:
        monkeypatch.delenv(missing)
    fakes = Fakes()
    assert await run(tmp_path, fakes) == 1
    assert _out(capsys)[0] == [line]
    assert fakes.requests == []
    assert _files(tmp_path) == []


@pytest.mark.asyncio
async def test_invalid_settings_print_one_fixed_line_without_the_value(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AI_MONTHLY_CAP_USD", "not-a-number-xyz")
    assert await run(tmp_path, Fakes()) == 1
    lines, _ = _out(capsys)
    assert lines == [
        "Settings are invalid: check AI_MODE, AI_MONTHLY_CAP_USD and DB_PING_TIMEOUT_S."
    ]


@pytest.mark.asyncio
async def test_records_each_demo_note_once_keyed_by_the_requested_model(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], database_url: str
) -> None:
    fakes = Fakes()
    assert await run(tmp_path, fakes) == 0
    assert len(fakes.requests) == 3
    expected = {f"{replay_key(request, LIVE_MODEL)}.json" for request in fakes.requests}
    assert set(_files(tmp_path)) == expected
    stored = json.loads((tmp_path / next(iter(expected))).read_text(encoding="utf-8"))
    assert stored["result"]["generation"]["model"] == ANSWERED_AS
    for request in fakes.requests:
        replayed = await ReplayProvider(tmp_path).draft_fdar(request)
        assert replayed.generation.provider == "replay"
    lines, err = _out(capsys)
    assert err == ""
    assert len(lines) == 4
    for case, line, request in zip(CASES, lines[:3], fakes.requests, strict=True):
        key = replay_key(request, LIVE_MODEL)
        assert line == f"{case.key}: recorded {key[:12]} $0.500000"
    assert lines[3] == "total: $1.500000 over 3 calls"


@pytest.mark.asyncio
async def test_a_recorded_note_is_skipped_without_a_call(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert await run(tmp_path, Fakes()) == 0
    capsys.readouterr()
    again = Fakes()
    assert await run(tmp_path, again) == 0
    assert again.requests == []
    lines, _ = _out(capsys)
    assert all("skipped (already recorded)" in line for line in lines[:3])
    assert lines[3] == "total: $0.000000 over 0 calls"


@pytest.mark.asyncio
async def test_force_records_again(tmp_path: Path) -> None:
    assert await run(tmp_path, Fakes()) == 0
    again = Fakes()
    assert await run(tmp_path, again, "--force") == 0
    assert len(again.requests) == 3


@pytest.mark.asyncio
async def test_stops_at_the_first_failure_and_a_second_run_pays_only_for_what_is_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    failing = Fakes(fail_on_call=2)
    assert await run(tmp_path, failing) == 1
    assert len(failing.requests) == 2  # no retry, no third call
    assert len(_files(tmp_path)) == 1
    lines, _ = _out(capsys)
    assert lines[1] == f"{CASES[1].key}: failed (ProviderUnavailable)"
    assert "boom" not in "".join(lines)
    resumed = Fakes()
    assert await run(tmp_path, resumed) == 0
    assert len(resumed.requests) == 2
    assert len(_files(tmp_path)) == 3


@pytest.mark.asyncio
async def test_cap_reached_records_nothing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_MONTHLY_CAP_USD", "1")
    engine = create_engine(database_url)
    try:
        generation = GenerationInfo(
            provider="anthropic",
            model=LIVE_MODEL,
            prompt_version="fdar-v1",
            input_tokens=1,
            output_tokens=1,
            cost_usd=Decimal(1),
            latency_ms=1,
        )
        await PgUsageRepository(engine).record(None, generation, SystemClock().now())
    finally:
        await engine.dispose()
    fakes = Fakes()
    assert await run(tmp_path, fakes) == 1
    assert fakes.requests == []
    assert _files(tmp_path) == []
    assert _out(capsys)[0][0] == f"{CASES[0].key}: failed (AiBudgetReached)"


@pytest.mark.asyncio
async def test_every_call_is_recorded_in_ai_usage(tmp_path: Path, database_url: str) -> None:
    assert await run(tmp_path, Fakes()) == 0
    engine = create_engine(database_url)
    try:
        async with engine.begin() as conn:
            rows = (await conn.execute(text("select job_id, model from ai_usage"))).all()
    finally:
        await engine.dispose()
    assert [(row[0], row[1]) for row in rows] == [(None, ANSWERED_AS)] * 3


@pytest.mark.asyncio
async def test_an_unseeded_database_says_to_run_make_seed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], database_url: str
) -> None:
    engine = create_engine(database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("update encounter set discharged_at = admitted_at"))
    finally:
        await engine.dispose()
    fakes = Fakes()
    assert await run(tmp_path, fakes) == 1
    assert _out(capsys)[0] == [
        "Not recording: the demo patients are not in the database. Run `make seed`."
    ]
    assert fakes.requests == []


@pytest.mark.asyncio
async def test_output_has_no_note_text_names_or_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert await run(tmp_path, Fakes(fail_on_call=3)) == 1
    out, err = capsys.readouterr()
    shown = (out + err).lower()
    assert KEY not in shown
    for case in CASES:
        for word in forbidden_words(case):
            assert word not in shown


@pytest.mark.asyncio
async def test_recordings_replay_through_the_api_worker(tmp_path: Path, database_url: str) -> None:
    """The recorder's requests equal the worker's: every demo note drafts from the recordings."""
    assert await run(tmp_path, Fakes()) == 0
    replay = ReplayProvider(tmp_path)
    clock = MutableClock()
    for case in CASES:
        clock.set(case.rough_note.written_at)
        async with (
            running_app(
                database_url, clock, ai_mode="replay", provider_for=lambda _patient: replay
            ) as app,
            client_for(app) as client,
        ):
            await sign_in(client, STAFF_NURSE[case.facility_key])
            posted = await post_note(client, case.patient_id, case.rough_note.text, key=case.key)
            assert posted.status_code == 202, posted.text
            await app.state.queue.drain()
            job = (await client.get(f"/api/v1/draft-jobs/{posted.json()['id']}")).json()
        assert job["status"] == "succeeded", job


@pytest.mark.asyncio
async def test_a_billed_answer_the_pipeline_refuses_is_counted_and_not_saved(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], database_url: str
) -> None:
    assert await run(tmp_path, Fakes(empty_draft=True)) == 1
    lines, _ = _out(capsys)
    assert lines == [
        f"{CASES[0].key}: failed (InvalidModelOutput) $0.500000",
        "total: $0.500000 over 1 call",
    ]
    assert _files(tmp_path) == []
    engine = create_engine(database_url)
    try:
        total, calls = await PgUsageRepository(engine).month_total(SystemClock().now())
    finally:
        await engine.dispose()
    assert (total, calls) == (Decimal("0.5"), 1)


@pytest.mark.asyncio
async def test_an_unreachable_database_prints_one_fixed_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:secret-pw@127.0.0.1:1/x")
    fakes = Fakes()
    assert await run(tmp_path, fakes) == 1
    out, err = capsys.readouterr()
    assert out.splitlines() == [
        "Not recording: the database is not reachable. Run `make up`, then try again."
    ]
    assert "Traceback" not in out + err
    assert "secret-pw" not in out + err
    assert fakes.requests == []


@pytest.mark.asyncio
async def test_an_unmigrated_database_says_to_run_make_migrate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], database_url: str
) -> None:
    engine = create_engine(database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("drop table encounter cascade"))
    finally:
        await engine.dispose()
    assert await run(tmp_path, Fakes()) == 1
    assert _out(capsys)[0] == ["Not recording: the database has no tables yet. Run `make migrate`."]
