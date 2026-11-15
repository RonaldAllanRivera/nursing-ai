"""Turn a rough note into a checked FDAR draft and its missing-items checklist."""

from collections.abc import Sequence

from nursing_core.domain import DomainModel
from nursing_core.domain.errors import InvalidModelOutput
from nursing_core.domain.model_output import DraftRequest, ModelLine
from nursing_core.domain.notes import (
    ChecklistItem,
    DraftLine,
    FdarDraft,
    FdarEntry,
    FdarSection,
    GenerationInfo,
    RoughNote,
)
from nursing_core.domain.patient import PatientRecord
from nursing_core.pipeline.checklist import missing_items_checklist
from nursing_core.pipeline.redact import redact, restore
from nursing_core.pipeline.text import prepare
from nursing_core.pipeline.verify import check_line
from nursing_core.ports import LlmProvider
from nursing_core.prompts import FDAR_PROMPT_VERSION


class PipelineResult(DomainModel):
    draft: FdarDraft
    checklist: list[ChecklistItem]
    generation: GenerationInfo


async def run_fdar_pipeline(
    note: RoughNote,
    patient: PatientRecord,
    earlier_shift_notes: Sequence[RoughNote],
    provider: LlmProvider,
    prompt_version: str = FDAR_PROMPT_VERSION,
) -> PipelineResult:
    redacted = redact(note.text, patient.identity)
    request = DraftRequest(
        redacted_text=redacted.text,
        note_format=note.note_format,
        locale=patient.facility.locale,
        prompt_version=prompt_version,
    )
    result = await provider.draft_fdar(request)
    if not result.output.entries:
        raise InvalidModelOutput("the model returned a draft with no entries")

    source = prepare(note.text)

    def checked(line_id: str, section: FdarSection, line: ModelLine) -> DraftLine:
        restored = line.model_copy(
            update={
                "text": restore(line.text, redacted.mapping),
                "source_quotes": [restore(q, redacted.mapping) for q in line.source_quotes],
            }
        )
        return check_line(line_id, section, restored, source, patient.facility.units)

    def section_lines(
        n: int, code: str, section: FdarSection, lines: list[ModelLine]
    ) -> list[DraftLine]:
        return [checked(f"e{n}-{code}{i}", section, line) for i, line in enumerate(lines, 1)]

    entries = [
        FdarEntry(
            focus=checked(f"e{n}-F", FdarSection.FOCUS, entry.focus),
            data=section_lines(n, "D", FdarSection.DATA, entry.data),
            action=section_lines(n, "A", FdarSection.ACTION, entry.action),
            response=section_lines(n, "R", FdarSection.RESPONSE, entry.response),
        )
        for n, entry in enumerate(result.output.entries, 1)
    ]

    texts = [
        earlier.text
        for earlier in earlier_shift_notes
        if earlier.id != note.id and earlier.written_at <= note.written_at
    ]
    checklist = missing_items_checklist(patient.context, [*texts, note.text], note.written_at)
    return PipelineResult(
        draft=FdarDraft(entries=entries), checklist=checklist, generation=result.generation
    )
