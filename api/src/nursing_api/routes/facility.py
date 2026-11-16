from typing import Annotated

from fastapi import APIRouter, Header, Response
from nursing_core.domain.errors import Forbidden, StaleVersion
from nursing_core.domain.facility import StoredFacility
from nursing_core.domain.shifts import shift_choices
from nursing_core.domain.users import can_see_facility
from nursing_core.ports import Clock

from nursing_api.deps import AdminDep, ClockDep, FacilitiesDep, SignedInDep
from nursing_api.problems import PreconditionRequired, problems
from nursing_api.routes import SIGNED_IN, etag_header
from nursing_api.schemas import FacilityOut, FacilitySettingsIn

router = APIRouter(prefix="/api/v1/facilities", tags=["facilities"], dependencies=SIGNED_IN)


def etag(version: int) -> str:
    return f'"f{version}"'


def facility_out(stored: StoredFacility, clock: Clock) -> FacilityOut:
    return FacilityOut(
        profile=stored.profile,
        version=stored.version,
        shift_choices=shift_choices(clock.now(), stored.profile),
    )


@router.get("", response_model=list[FacilityOut], responses=problems(401))
async def list_facilities(
    signed_in: SignedInDep, clock: ClockDep, facilities: FacilitiesDep
) -> list[FacilityOut]:
    """A nurse's own facility, or every facility for the admin."""
    user = signed_in.user
    return [
        facility_out(stored, clock)
        for stored in await facilities.list_facilities()
        if can_see_facility(user.role, user.facility_key, stored.profile.key)
    ]


@router.get(
    "/{facility_key}",
    response_model=FacilityOut,
    responses={200: {"headers": etag_header()}, **problems(401, 403, 404, 422)},
)
async def get_facility(
    facility_key: str,
    response: Response,
    signed_in: SignedInDep,
    clock: ClockDep,
    facilities: FacilitiesDep,
) -> FacilityOut:
    # A nurse asking for another or an unknown facility gets 403: keys are public names.
    user = signed_in.user
    if not can_see_facility(user.role, user.facility_key, facility_key):
        raise Forbidden("not your facility")
    stored = await facilities.get_facility(facility_key)
    response.headers["ETag"] = etag(stored.version)
    return facility_out(stored, clock)


@router.put(
    "/{facility_key}",
    response_model=FacilityOut,
    responses={200: {"headers": etag_header()}, **problems(401, 403, 404, 412, 422, 428)},
)
async def update_facility(
    facility_key: str,
    settings: FacilitySettingsIn,
    response: Response,
    admin: AdminDep,
    clock: ClockDep,
    facilities: FacilitiesDep,
    if_match: Annotated[
        str | None, Header(alias="If-Match", description="Required: 428 without it")
    ] = None,
) -> FacilityOut:
    """The admin edits a facility's settings. Notes already written keep their shift."""
    # Order: 401, 403 (the admin dependency), body 422 (the framework), 428, 404, 412, save.
    if not if_match:
        raise PreconditionRequired
    current = await facilities.get_facility(facility_key)
    if if_match != etag(current.version):
        # Only the exact current ETag passes; a race is caught by the repository's own check.
        raise StaleVersion("the facility has changed")
    saved = await facilities.update_facility(
        facility_key, settings, current.version, changed_by=admin.id
    )
    response.headers["ETag"] = etag(saved.version)
    return facility_out(saved, clock)
