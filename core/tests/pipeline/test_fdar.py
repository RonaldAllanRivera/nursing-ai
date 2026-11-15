"""The whole draft pipeline with a fake provider: the demo cases must come out exactly."""

from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from nursing_core.demo import DEMO_FACILITIES, DemoCase, load_demo_cases
from nursing_core.domain.errors import AiBudgetReached, InvalidModelOutput
from nursing_core.domain.model_output import (
    DraftRequest,
    ModelFdarDraft,
    ModelFdarEntry,
    ModelLine,
    ProviderResult,
)
from nursing_core.domain.notes import ChecklistRule, RoughNote
from nursing_core.domain.patient import PatientRecord, PatientSummary
from nursing_core.pipeline.fdar import PipelineResult, run_fdar_pipeline
from nursing_core.prompts import FDAR_PROMPT_VERSION
from nursing_core.providers.fake import FakeProvider

CASES = load_demo_cases()
CASE_IDS = [case.key for case in CASES]


def _patient(case: DemoCase) -> PatientRecord:
    return PatientRecord(
        summary=PatientSummary(
            id=case.patient_id,
            display_name=case.display_name,
            age=case.age,
            sex=case.sex,
            ward=case.ward,
            bed_label=case.bed_label,
            facility_key=case.facility_key,
        ),
        encounter_id=case.rough_note.encounter_id,
        identity=case.patient,
        context=case.context,
        facility=next(f for f in DEMO_FACILITIES if f.key == case.facility_key),
    )


def _line(text: str) -> ModelLine:
    return ModelLine(text=text, source_quotes=[], own_wording=True)


def _entry(
    focus: str = "Pain",
    data: list[ModelLine] | None = None,
    action: list[ModelLine] | None = None,
    response: list[ModelLine] | None = None,
) -> ModelFdarEntry:
    return ModelFdarEntry(
        focus=_line(focus),
        data=data or [],
        action=action or [],
        response=response or [],
    )


def _output(*entries: ModelFdarEntry) -> ModelFdarDraft:
    return ModelFdarDraft(entries=list(entries))


class _Capturing:
    """Records every request, then answers like the fake provider."""

    def __init__(self, inner: FakeProvider) -> None:
        self.inner = inner
        self.requests: list[DraftRequest] = []

    async def draft_fdar(self, request: DraftRequest) -> ProviderResult:
        self.requests.append(request)
        return await self.inner.draft_fdar(request)


class _Failing:
    async def draft_fdar(self, request: DraftRequest) -> ProviderResult:
        raise AiBudgetReached("the monthly cap is reached")


def _note(case: DemoCase, **update: Any) -> RoughNote:
    return case.rough_note.model_copy(update=update)


def _missing(result: PipelineResult, rule: ChecklistRule) -> bool:
    return any(item.missing for item in result.checklist if item.rule is rule)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
async def test_demo_cases_reproduce_expected_output(case: DemoCase) -> None:
    result = await run_fdar_pipeline(
        case.rough_note, _patient(case), [], FakeProvider(case.model_output, case.patient)
    )
    assert isinstance(result, PipelineResult)
    assert result.draft == case.expected_draft
    assert result.checklist == case.expected_checklist


@pytest.mark.asyncio
async def test_empty_response_stays_empty() -> None:
    case = CASES[0]
    result = await run_fdar_pipeline(
        case.rough_note, _patient(case), [], FakeProvider(_output(_entry(response=[])))
    )
    assert result.draft.entries[0].response == []


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
async def test_model_never_sees_a_known_name(case: DemoCase) -> None:
    identity = case.patient
    names = [
        identity.given_name,
        identity.family_name,
        *identity.nicknames,
        *(relative.name for relative in identity.relatives),
    ]
    text = f"{' and '.join(names)} calm. SSN 000-12-3456 given. BP 120/80."
    provider = _Capturing(FakeProvider(_output(_entry()), identity))
    await run_fdar_pipeline(_note(case, text=text), _patient(case), [], provider)
    sent = provider.requests[0].redacted_text
    for secret in (*names, "000-12-3456"):
        assert secret not in sent
    assert "BP 120/80" in sent


@pytest.mark.asyncio
async def test_request_uses_the_facility_locale_note_format_and_prompt_version() -> None:
    case = next(c for c in CASES if c.facility_key == "us-demo")
    patient = _patient(case)
    custom = _Capturing(FakeProvider(_output(_entry())))
    await run_fdar_pipeline(case.rough_note, patient, [], custom, prompt_version="fdar-test")
    request = custom.requests[0]
    assert request.locale is patient.facility.locale
    assert request.note_format is case.rough_note.note_format
    assert request.prompt_version == "fdar-test"
    default = _Capturing(FakeProvider(_output(_entry())))
    await run_fdar_pipeline(case.rough_note, patient, [], default)
    assert default.requests[0].prompt_version == FDAR_PROMPT_VERSION


@pytest.mark.asyncio
async def test_line_ids_number_each_section_per_entry() -> None:
    case = CASES[0]
    output = _output(
        _entry("A", data=[_line("d1"), _line("d2")], action=[_line("a1")]),
        _entry("B", data=[_line("d")], action=[_line("a1"), _line("a2")], response=[_line("r")]),
    )
    result = await run_fdar_pipeline(case.rough_note, _patient(case), [], FakeProvider(output))
    ids = [[line.id for line in entry.lines()] for entry in result.draft.entries]
    assert ids == [
        ["e1-F", "e1-D1", "e1-D2", "e1-A1"],
        ["e2-F", "e2-D1", "e2-A1", "e2-A2", "e2-R1"],
    ]


@pytest.mark.asyncio
async def test_earlier_notes_count_and_later_or_duplicate_notes_are_skipped() -> None:
    case = CASES[0]
    tube = case.context.lines_tubes[0].kind
    patient = _patient(case)
    current = _note(case, text="Patient resting.")
    earlier = current.model_copy(
        update={
            "id": uuid4(),
            "text": f"{tube} site clean and dry.",
            "written_at": current.written_at - timedelta(hours=1),
        }
    )
    later = earlier.model_copy(
        update={"id": uuid4(), "written_at": current.written_at + timedelta(hours=1)}
    )
    same_id = earlier.model_copy(update={"id": current.id})
    provider = FakeProvider(_output(_entry()))
    alone = await run_fdar_pipeline(current, patient, [], provider)
    counted = await run_fdar_pipeline(current, patient, [earlier], provider)
    skipped = await run_fdar_pipeline(current, patient, [later, same_id], provider)
    assert counted.checklist != alone.checklist
    assert skipped.checklist == alone.checklist
    assert _missing(alone, ChecklistRule.LINE_OR_TUBE)
    assert not _missing(counted, ChecklistRule.LINE_OR_TUBE)


@pytest.mark.asyncio
async def test_output_without_entries_is_invalid() -> None:
    case = CASES[0]
    with pytest.raises(InvalidModelOutput):
        await run_fdar_pipeline(case.rough_note, _patient(case), [], FakeProvider(_output()))


@pytest.mark.asyncio
async def test_provider_errors_pass_through() -> None:
    case = CASES[0]
    with pytest.raises(AiBudgetReached):
        await run_fdar_pipeline(case.rough_note, _patient(case), [], _Failing())
