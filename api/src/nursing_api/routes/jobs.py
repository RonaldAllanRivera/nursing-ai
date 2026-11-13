from uuid import UUID

from fastapi import APIRouter

from nursing_api.problems import problems
from nursing_api.routes import SIGNED_IN, not_built
from nursing_api.schemas import DraftJobOut

router = APIRouter(prefix="/api/v1/draft-jobs", tags=["notes"], dependencies=SIGNED_IN)


@router.get("/{job_id}", response_model=DraftJobOut, responses=problems(401, 403, 404, 422))
async def get_job(job_id: UUID) -> DraftJobOut:
    not_built()
