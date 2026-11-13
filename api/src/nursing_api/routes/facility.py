from typing import Annotated

from fastapi import APIRouter, Header

from nursing_api.problems import problems
from nursing_api.routes import etag_header, not_built
from nursing_api.schemas import FacilityOut, FacilitySettingsIn

router = APIRouter(prefix="/api/v1/facilities", tags=["facilities"])


@router.get("", response_model=list[FacilityOut], responses=problems(401))
async def list_facilities() -> list[FacilityOut]:
    """A nurse's own facility, or every facility for the admin."""
    not_built()


@router.get(
    "/{facility_key}",
    response_model=FacilityOut,
    responses={200: {"headers": etag_header()}, **problems(401, 403, 404, 422)},
)
async def get_facility(facility_key: str) -> FacilityOut:
    not_built()


@router.put(
    "/{facility_key}",
    response_model=FacilityOut,
    responses={200: {"headers": etag_header()}, **problems(401, 403, 404, 412, 422, 428)},
)
async def update_facility(
    facility_key: str,
    settings: FacilitySettingsIn,
    if_match: Annotated[
        str | None, Header(alias="If-Match", description="Required: 428 without it")
    ] = None,
) -> FacilityOut:
    """The admin edits a facility's settings. Notes already written keep their shift."""
    not_built()
