from uuid import UUID

from fastapi import APIRouter, Response

from nursing_api.problems import not_built, problems
from nursing_api.routes import CSRF, SIGNED_IN
from nursing_api.schemas import InviteIn, PinIn, UserOut

router = APIRouter(prefix="/api/v1/users", tags=["staff"], dependencies=SIGNED_IN)


@router.get("", response_model=list[UserOut], responses=problems(401, 403, 423))
async def list_staff() -> Response:
    """Everyone invited, for the admin; a head nurse's own facility. Personas aren't listed."""
    return not_built()


@router.post(
    "",
    status_code=201,
    response_model=UserOut,
    responses=problems(401, 403, 409, 422, 423),
    dependencies=CSRF,
)
async def invite(body: InviteIn) -> Response:
    """The admin invites a Google account by email, with a role and a facility."""
    return not_built()


@router.post(
    "/{user_id}/revoke",
    response_model=UserOut,
    responses=problems(401, 403, 404, 422, 423),
    dependencies=CSRF,
)
async def revoke(user_id: UUID, body: PinIn) -> Response:
    """The admin ends someone's access and sessions; the row stays for their signed notes."""
    return not_built()


@router.post(
    "/{user_id}/pin-reset",
    response_model=UserOut,
    responses=problems(401, 403, 404, 422, 423),
    dependencies=CSRF,
)
async def reset_pin(user_id: UUID, body: PinIn) -> Response:
    """In person: the admin, or a head nurse for her facility's nurses, clears a locked PIN."""
    return not_built()
