from uuid import UUID

from fastapi import APIRouter
from nursing_core.domain.patient import PatientSummary

from nursing_api.problems import problems
from nursing_api.routes import SIGNED_IN, not_built
from nursing_api.schemas import PatientDetail

router = APIRouter(prefix="/api/v1/patients", tags=["patients"], dependencies=SIGNED_IN)


@router.get("", response_model=list[PatientSummary], responses=problems(401, 403))
async def list_patients() -> list[PatientSummary]:
    """The patients of the nurse's facility (403 for the admin, who doesn't chart)."""
    not_built()


@router.get("/{patient_id}", response_model=PatientDetail, responses=problems(401, 403, 404, 422))
async def get_patient(patient_id: UUID) -> PatientDetail:
    """The patient and this shift's notes."""
    not_built()
