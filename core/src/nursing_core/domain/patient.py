"""The patient: region-neutral identity (what redaction removes) and the mock-HIS context."""

from datetime import date
from typing import Annotated
from uuid import UUID

from pydantic import AwareDatetime, NonNegativeInt, StringConstraints

from nursing_core.domain import DomainModel
from nursing_core.domain.facility import FacilityProfile
from nursing_core.domain.units import Quantity

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Relative(DomainModel):
    name: Text
    relation: Text


class PatientIdentity(DomainModel):
    """Name parts and identifiers as the record holds them, for any region."""

    given_name: Text
    middle_name: str | None
    family_name: Text
    suffix: str | None
    nicknames: list[str]
    relatives: list[Relative]
    record_number: Text
    birth_date: date
    address: str | None
    postal_code: str | None


class LineOrTube(DomainModel):
    kind: str
    description: str
    aliases: list[str]


class MedicineDue(DomainModel):
    name: str
    dose: str
    route: str
    due_at: AwareDatetime
    aliases: list[str]


class PendingTest(DomainModel):
    name: str
    sent_at: AwareDatetime | None
    aliases: list[str]


class FallRisk(DomainModel):
    scale: str
    score: NonNegativeInt
    high: bool


class Vitals(DomainModel):
    taken_at: AwareDatetime
    temperature: Quantity | None
    pulse: Quantity | None
    resp_rate: Quantity | None
    bp_systolic: Quantity | None
    bp_diastolic: Quantity | None
    spo2: Quantity | None
    weight: Quantity | None


class PatientContext(DomainModel):
    """Read-only context from the mock HIS. Code status is kept but never flagged."""

    allergies: list[str] | None  # None: not recorded; []: NKDA, which counts as recorded
    code_status: str
    lines_tubes: list[LineOrTube]
    medicines_due: list[MedicineDue]
    pending_tests: list[PendingTest]
    latest_vitals: Vitals | None
    fall_risk: FallRisk | None

    @property
    def allergies_recorded(self) -> bool:
        return self.allergies is not None


class PatientSummary(DomainModel):
    id: UUID
    display_name: str
    age: NonNegativeInt
    sex: str
    ward: str
    bed_label: str
    facility_key: str


class PatientRecord(DomainModel):
    summary: PatientSummary
    encounter_id: UUID
    identity: PatientIdentity
    context: PatientContext
    facility: FacilityProfile
