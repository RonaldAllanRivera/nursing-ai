"""Three synthetic demo cases, the two demo facilities and the demo personas.

Each case holds a patient, a rough note, what the fake provider returns for it, and the draft
and checklist the pipeline must produce. The pipeline's acceptance test, the API's seed and the
web app's mock data all read these same files. Every person in them is invented (SYNTHETIC).
"""

import json
from importlib import resources
from typing import Literal
from uuid import UUID

from pydantic import NonNegativeInt

from nursing_core.domain import DomainModel
from nursing_core.domain.facility import FacilityProfile, preset
from nursing_core.domain.model_output import ModelFdarDraft
from nursing_core.domain.notes import ChecklistItem, FdarDraft, RoughNote
from nursing_core.domain.patient import PatientContext, PatientIdentity
from nursing_core.domain.users import Role


class DemoCase(DomainModel):
    key: str
    synthetic: Literal[True]
    facility_key: str
    ward: str
    bed_label: str
    patient_id: UUID
    display_name: str
    age: NonNegativeInt
    sex: str
    patient: PatientIdentity
    context: PatientContext
    rough_note: RoughNote
    model_output: ModelFdarDraft  # in redacted form: names are tokens such as [RELATIVE_1]
    expected_draft: FdarDraft
    expected_checklist: list[ChecklistItem]


class DemoPersona(DomainModel):
    id: UUID
    display_name: str
    initials: str
    role: Role
    facility_key: str | None  # None for the admin, who works across every facility


DEMO_FACILITIES: list[FacilityProfile] = [
    preset("PH", "ph-demo", "SYNTHETIC Demo Hospital (PH)"),
    preset("US", "us-demo", "SYNTHETIC Demo Hospital (US)"),
]


def _persona(n: int, name: str, initials: str, role: Role, key: str | None) -> DemoPersona:
    return DemoPersona(
        id=UUID(f"00000000-0000-4000-8000-{n:012d}"),
        display_name=name,
        initials=initials,
        role=role,
        facility_key=key,
    )


# Invented people. Screens always show the role next to the name, so a visitor knows whether
# they are signed in as a nurse or as the admin.
DEMO_PERSONAS: list[DemoPersona] = [
    _persona(101, "Sarah Navarro, RN", "SN", Role.STAFF_NURSE, "ph-demo"),
    _persona(102, "Grace Villareal, RN", "GV", Role.HEAD_NURSE, "ph-demo"),
    _persona(201, "Emily Carter, RN", "EC", Role.STAFF_NURSE, "us-demo"),
    _persona(202, "Megan Brooks, RN", "MB", Role.HEAD_NURSE, "us-demo"),
    _persona(901, "Victor Lazaro", "VL", Role.ADMIN, None),
]


def load_demo_cases() -> list[DemoCase]:
    folder = resources.files(__package__).joinpath("cases")
    files = sorted(
        (entry for entry in folder.iterdir() if entry.name.endswith(".json")),
        key=lambda entry: entry.name,
    )
    return [
        DemoCase.model_validate(json.loads(entry.read_text(encoding="utf-8"))) for entry in files
    ]
