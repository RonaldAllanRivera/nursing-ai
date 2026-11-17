from typing import Annotated

from fastapi import APIRouter, Header, Request, Response
from nursing_core.domain.errors import Forbidden, StaleVersion
from nursing_core.domain.facility import StoredFacility
from nursing_core.domain.shifts import shift_choices
from nursing_core.domain.users import can_see_facility
from nursing_core.ports import Clock
from nursing_core.storage.repositories import (
    PgFacilityRepository,
    PgSessionRepository,
    PgUserRepository,
)

from nursing_api.auth.pin_check import SessionEnded, prove_pin, session_ended_response
from nursing_api.deps import (
    AdminDep,
    ClockDep,
    FacilitiesDep,
    SessionsDep,
    SignedIn,
    SignedInDep,
    UsersDep,
)
from nursing_api.problems import PreconditionRequired, problems
from nursing_api.routes import CSRF, SIGNED_IN, etag_header
from nursing_api.schemas import FacilityOut, FacilityUpdateIn, PinIn
from nursing_api.settings import Settings

router = APIRouter(prefix="/api/v1/facilities", tags=["facilities"], dependencies=SIGNED_IN)


def etag(version: int) -> str:
    return f'"f{version}"'


def facility_out(stored: StoredFacility, clock: Clock) -> FacilityOut:
    return FacilityOut(
        profile=stored.profile,
        version=stored.version,
        shift_choices=shift_choices(clock.now(), stored.profile),
    )


@router.get("", response_model=list[FacilityOut], responses=problems(401, 423))
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
    responses={200: {"headers": etag_header()}, **problems(401, 403, 404, 422, 423)},
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


IfMatch = Annotated[str | None, Header(alias="If-Match", description="Required: 428 without it")]
SAVE = {200: {"headers": etag_header()}, **problems(401, 403, 404, 412, 422, 423, 428)}


async def checked_save(
    facility_key: str,
    if_match: str | None,
    pin: str,
    signed_in: SignedIn,
    facilities: PgFacilityRepository,
    users: PgUserRepository,
    sessions: PgSessionRepository,
    clock: Clock,
) -> StoredFacility:
    """What a settings save and a demo reset both need first: the If-Match (428 missing, 412 not
    the current ETag) and then the PIN. Returns the facility as read; the repository checks its
    version again under the row lock, so a save that lands during the PIN check is never lost."""
    if not if_match:
        raise PreconditionRequired
    current = await facilities.get_facility(facility_key)
    if if_match != etag(current.version):
        raise StaleVersion("the facility has changed")
    await prove_pin(signed_in, pin, users=users, sessions=sessions, clock=clock)
    return current


@router.put("/{facility_key}", response_model=FacilityOut, responses=SAVE, dependencies=CSRF)
async def update_facility(
    facility_key: str,
    body: FacilityUpdateIn,
    response: Response,
    admin: AdminDep,
    clock: ClockDep,
    facilities: FacilitiesDep,
    users: UsersDep,
    sessions: SessionsDep,
    signed_in: SignedInDep,
    if_match: IfMatch = None,
) -> FacilityOut | Response:
    """The admin edits a facility's settings, with their PIN. Notes already written keep their
    shift."""
    # Order: 401, 403 (the admin dependency), body 422 (the framework), 428, 404, 412, save.
    try:
        current = await checked_save(
            facility_key, if_match, body.pin, signed_in, facilities, users, sessions, clock
        )
    except SessionEnded:
        return session_ended_response()
    saved = await facilities.update_facility(
        facility_key, body.settings(), current.version, changed_by=admin.id
    )
    response.headers["ETag"] = etag(saved.version)
    return facility_out(saved, clock)


@router.post("/{facility_key}/reset", response_model=FacilityOut, responses=SAVE, dependencies=CSRF)
async def reset_facility(
    facility_key: str,
    body: PinIn,
    request: Request,
    response: Response,
    admin: AdminDep,
    clock: ClockDep,
    facilities: FacilitiesDep,
    users: UsersDep,
    sessions: SessionsDep,
    signed_in: SignedInDep,
    if_match: IfMatch = None,
) -> FacilityOut | Response:
    """The demo's admin persona puts a facility back to its preset at once."""
    settings: Settings = request.app.state.settings
    if settings.app_env != "demo" or not admin.persona:
        raise Forbidden("only the demo's admin persona resets settings")
    try:
        current = await checked_save(
            facility_key, if_match, body.pin, signed_in, facilities, users, sessions, clock
        )
    except SessionEnded:
        return session_ended_response()
    saved = await facilities.reset_to_preset(facility_key, clock.now(), current.version)
    response.headers["ETag"] = etag(saved.version)
    return facility_out(saved, clock)
