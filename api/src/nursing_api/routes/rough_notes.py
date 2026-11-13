from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header

from nursing_api.problems import problems
from nursing_api.routes import SIGNED_IN, not_built
from nursing_api.schemas import DraftJobOut, RoughNoteIn

router = APIRouter(prefix="/api/v1/patients", tags=["notes"], dependencies=SIGNED_IN)


@router.post(
    "/{patient_id}/rough-notes",
    status_code=202,
    response_model=DraftJobOut,
    responses={
        202: {
            "headers": {
                "Location": {"description": "The draft job to poll", "schema": {"type": "string"}}
            }
        },
        **problems(401, 403, 404, 422, 428),
    },
)
async def add_rough_note(
    patient_id: UUID,
    body: RoughNoteIn,
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description="Required: 428 without it. The same key and text return the first job.",
        ),
    ] = None,
) -> DraftJobOut:
    """Saves the rough note in the session's shift and starts a draft job."""
    not_built()
