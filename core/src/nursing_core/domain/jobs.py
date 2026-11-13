"""Draft jobs: a rough note becomes a draft in the background."""

from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import AwareDatetime, model_validator

from nursing_core.domain import DomainModel


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class JobFailure(StrEnum):
    AI_BUDGET_REACHED = "ai_budget_reached"
    MODEL_REFUSED = "model_refused"
    INVALID_OUTPUT = "invalid_output"
    PROVIDER_ERROR = "provider_error"
    REPLAY_MISSING = "replay_missing"


class DraftJob(DomainModel):
    id: UUID
    rough_note_id: UUID
    status: JobStatus
    failure: JobFailure | None
    note_id: UUID | None
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def _outcome_matches_status(self) -> Self:
        if (self.status is JobStatus.FAILED) != (self.failure is not None):
            raise ValueError("a failed job, and only a failed job, has a failure")
        if (self.status is JobStatus.SUCCEEDED) != (self.note_id is not None):
            raise ValueError("a succeeded job, and only a succeeded job, has a note")
        return self
