from fastapi import APIRouter, Response

from nursing_api.problems import not_built
from nursing_api.schemas import SignInOptionsOut

router = APIRouter(prefix="/api/v1", tags=["session"])


@router.get("/sign-in-options", response_model=SignInOptionsOut)
async def sign_in_options() -> Response:
    """What the sign-in page offers: Google, the demo personas and their PIN. Reads no database."""
    return not_built()
