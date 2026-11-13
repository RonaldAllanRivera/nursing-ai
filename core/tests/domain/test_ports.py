"""The ports: in-test fakes satisfy them, which pyright checks through the typed assignments."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from nursing_core.clock import FixedClock, SystemClock
from nursing_core.domain.facility import FacilitySettings, StoredFacility, preset
from nursing_core.domain.hashing import SignedNote
from nursing_core.domain.jobs import DraftJob, JobFailure, ShiftEntry
from nursing_core.domain.model_output import DraftRequest, ProviderResult
from nursing_core.domain.notes import Discard, Note, RoughNote
from nursing_core.domain.patient import PatientRecord, PatientSummary
from nursing_core.domain.shifts import ShiftRef
from nursing_core.ports import (
    Clock,
    DraftJobQueue,
    FacilityRepository,
    LlmProvider,
    NoteRepository,
    PatientRepository,
)


class FakeProvider:
    async def draft_fdar(self, request: DraftRequest) -> ProviderResult:
        raise NotImplementedError


class FakeQueue:
    def __init__(self) -> None:
        self.queued: list[UUID] = []

    async def enqueue(self, job_id: UUID) -> None:
        self.queued.append(job_id)


class FakeFacilities:
    async def list_facilities(self) -> list[StoredFacility]:
        return [StoredFacility(profile=preset("PH", "ph-demo", "SYNTHETIC"), version=1)]

    async def get_facility(self, key: str) -> StoredFacility:
        raise NotImplementedError

    async def update_facility(
        self, key: str, settings: FacilitySettings, expected_version: int, changed_by: UUID
    ) -> StoredFacility:
        raise NotImplementedError


class FakePatients:
    async def list_patients(self, facility_key: str) -> list[PatientSummary]:
        return []

    async def get_patient(self, patient_id: UUID) -> PatientRecord:
        raise NotImplementedError

    async def get_patient_by_encounter(self, encounter_id: UUID) -> PatientRecord:
        raise NotImplementedError


class FakeNotes:
    async def add_rough_note(
        self, note: RoughNote, idempotency_key: str, body_hash: str
    ) -> tuple[RoughNote, DraftJob]:
        raise NotImplementedError

    async def get_rough_note(self, rough_note_id: UUID) -> RoughNote:
        raise NotImplementedError

    async def get_job(self, job_id: UUID) -> DraftJob:
        raise NotImplementedError

    async def claim_job(self, job_id: UUID) -> RoughNote | None:
        return None

    async def complete_job(self, job_id: UUID, note: Note) -> None:
        raise NotImplementedError

    async def fail_job(self, job_id: UUID, failure: JobFailure) -> None:
        raise NotImplementedError

    async def shift_rough_notes(self, encounter_id: UUID, shift: ShiftRef) -> list[RoughNote]:
        return []

    async def shift_entries(self, encounter_id: UUID, shift: ShiftRef) -> list[ShiftEntry]:
        return []

    async def get_note(self, note_id: UUID) -> Note:
        raise NotImplementedError

    async def save_draft(self, note: Note, expected_version: int) -> Note:
        raise NotImplementedError

    async def sign(self, note_id: UUID, expected_version: int, record: SignedNote) -> Note:
        raise NotImplementedError

    async def discard(self, note_id: UUID, expected_version: int, discard: Discard) -> Note:
        raise NotImplementedError


@pytest.mark.asyncio
async def test_in_test_fakes_satisfy_the_ports() -> None:
    clocks: list[Clock] = [SystemClock(), FixedClock(datetime(2026, 11, 12, tzinfo=UTC))]
    provider: LlmProvider = FakeProvider()
    queue: DraftJobQueue = FakeQueue()
    facilities: FacilityRepository = FakeFacilities()
    patients: PatientRepository = FakePatients()
    notes: NoteRepository = FakeNotes()

    assert all(clock.now().tzinfo is UTC for clock in clocks)
    assert provider is not None
    job_id = UUID("00000000-0000-4000-8000-000000000001")
    await queue.enqueue(job_id)
    assert [stored.profile.key for stored in await facilities.list_facilities()] == ["ph-demo"]
    assert await patients.list_patients("ph-demo") == []
    assert await notes.claim_job(job_id) is None
