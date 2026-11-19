from uuid import UUID

from fastapi import APIRouter
from nursing_core.demo import load_demo_cases
from nursing_core.domain.patient import PatientSummary

from nursing_api.deps import NotesDep, NurseDep, PatientsDep, QueueDep, ensure_own_facility
from nursing_api.problems import problems
from nursing_api.routes import SIGNED_IN
from nursing_api.routes.jobs import job_out, resend_stuck
from nursing_api.schemas import PatientDetail, ShiftNoteOut

# Replay mode only knows the demo cases' rough notes, so a demo patient offers hers.
DEMO_NOTES = {case.patient_id: case.rough_note.text for case in load_demo_cases()}

router = APIRouter(prefix="/api/v1/patients", tags=["patients"], dependencies=SIGNED_IN)


@router.get("", response_model=list[PatientSummary], responses=problems(401, 403, 423))
async def list_patients(nurse: NurseDep, patients: PatientsDep) -> list[PatientSummary]:
    """The patients of the nurse's facility (403 for the admin, who doesn't chart)."""
    return await patients.list_patients(nurse.facility_key)


@router.get(
    "/{patient_id}", response_model=PatientDetail, responses=problems(401, 403, 404, 422, 423)
)
async def get_patient(
    patient_id: UUID, nurse: NurseDep, patients: PatientsDep, notes: NotesDep, queue: QueueDep
) -> PatientDetail:
    """The patient and this shift's notes."""
    patient = await patients.get_patient(patient_id)
    ensure_own_facility(nurse, patient)
    entries = await notes.shift_entries(
        patient.encounter_id, nurse.shift, persona=nurse.user.persona
    )
    await resend_stuck(notes, queue, [entry.job for entry in entries])
    return PatientDetail(
        summary=patient.summary,
        shift=nurse.shift,
        notes=[
            ShiftNoteOut(
                rough_note_id=entry.rough_note.id,
                written_at=entry.rough_note.written_at,
                job=job_out(entry.job),
                note_status=entry.note_status,
            )
            for entry in entries
        ],
        demo_note=DEMO_NOTES.get(patient.summary.id),
    )
