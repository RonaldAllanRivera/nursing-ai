"""The ports core depends on; adapters live at the edges (the API, storage, providers).

The draft pipeline itself takes data and a provider, never a repository, so its tests need no
database.
"""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from nursing_core.domain.facility import FacilitySettings, StoredFacility
from nursing_core.domain.hashing import SignedNote
from nursing_core.domain.jobs import DraftJob, JobFailure
from nursing_core.domain.model_output import DraftRequest, ProviderResult
from nursing_core.domain.notes import Discard, Note, RoughNote
from nursing_core.domain.patient import PatientRecord, PatientSummary
from nursing_core.domain.shifts import ShiftRef


class Clock(Protocol):
    def now(self) -> datetime:
        """An aware datetime in UTC."""
        ...


class LlmProvider(Protocol):
    async def draft_fdar(self, request: DraftRequest) -> ProviderResult:
        """Raises AiBudgetReached, ModelRefused, InvalidModelOutput, ProviderUnavailable or
        ReplayMissing."""
        ...


class DraftJobQueue(Protocol):
    async def enqueue(self, job_id: UUID) -> None: ...


class FacilityRepository(Protocol):
    async def list_facilities(self) -> list[StoredFacility]: ...

    async def get_facility(self, key: str) -> StoredFacility:
        """Raises NotFound."""
        ...

    async def update_facility(
        self, key: str, settings: FacilitySettings, expected_version: int, changed_by: UUID
    ) -> StoredFacility:
        """Saves the admin's edit and its history row. Raises NotFound or StaleVersion."""
        ...


class PatientRepository(Protocol):
    async def list_patients(self, facility_key: str) -> list[PatientSummary]: ...

    async def get_patient(self, patient_id: UUID) -> PatientRecord:
        """Raises NotFound."""
        ...


class NoteRepository(Protocol):
    async def add_rough_note(
        self, note: RoughNote, idempotency_key: str, body_hash: str
    ) -> tuple[RoughNote, DraftJob]:
        """The same key and body return the first pair; the same key with another body raises
        IdempotencyConflict."""
        ...

    async def get_rough_note(self, rough_note_id: UUID) -> RoughNote: ...

    async def get_job(self, job_id: UUID) -> DraftJob: ...

    async def claim_job(self, job_id: UUID) -> RoughNote | None:
        """Moves a queued job to running and returns its rough note; None if already claimed."""
        ...

    async def complete_job(self, job_id: UUID, note: Note) -> None: ...

    async def fail_job(self, job_id: UUID, failure: JobFailure) -> None: ...

    async def shift_rough_notes(self, encounter_id: UUID, shift: ShiftRef) -> list[RoughNote]:
        """This shift's rough notes for the encounter, oldest first."""
        ...

    async def get_note(self, note_id: UUID) -> Note: ...

    async def save_draft(self, note: Note, expected_version: int) -> Note:
        """Raises StaleVersion or NoteLocked."""
        ...

    async def sign(self, note_id: UUID, expected_version: int, record: SignedNote) -> Note:
        """Writes the signed record. Raises StaleVersion or NoteLocked."""
        ...

    async def discard(self, note_id: UUID, expected_version: int, discard: Discard) -> Note:
        """Raises StaleVersion or NoteLocked."""
        ...
