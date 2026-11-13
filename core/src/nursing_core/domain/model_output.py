"""What the provider returns: no statuses and no spans, since code computes those.

This schema is sent to the model as its structured-output format. It is the same for every
patient and never holds patient data in an enum, const or pattern, because the API caches
schemas apart from the messages.
"""

from nursing_core.domain import DomainModel
from nursing_core.domain.facility import Locale, NoteFormat
from nursing_core.domain.notes import GenerationInfo


class ModelLine(DomainModel):
    text: str
    source_quotes: list[str]
    own_wording: bool


class ModelFdarEntry(DomainModel):
    focus: ModelLine
    data: list[ModelLine]
    action: list[ModelLine]
    response: list[ModelLine]


class ModelFdarDraft(DomainModel):
    entries: list[ModelFdarEntry]


class DraftRequest(DomainModel):
    redacted_text: str  # known identifiers already replaced by tokens
    note_format: NoteFormat
    locale: Locale
    prompt_version: str


class ProviderResult(DomainModel):
    output: ModelFdarDraft
    generation: GenerationInfo
