from typing import Annotated

from fastapi import APIRouter, Request, Response, Security
from nursing_core.demo import DEMO_PERSONAS
from nursing_core.domain.shifts import ShiftRef, default_shift, shift_choices
from nursing_core.storage.repositories import SESSION_LIFETIME, StoredUser

from nursing_api.deps import (
    ClockDep,
    FacilitiesDep,
    NurseDep,
    SessionsDep,
    SignedInDep,
    UsersDep,
)
from nursing_api.problems import FieldError, problem_response, problems
from nursing_api.routes import SESSION_COOKIE, SIGNED_IN
from nursing_api.schemas import PersonaOut, SessionIn, SessionOut, ShiftChoiceIn
from nursing_api.settings import Settings

router = APIRouter(prefix="/api/v1", tags=["session"])

COOKIE = "sl_session"


def session_out(user: StoredUser, shift: ShiftRef | None) -> SessionOut:
    return SessionOut(
        user_id=user.id,
        display_name=user.display_name,
        initials=user.initials,
        role=user.role,
        facility_key=user.facility_key,
        shift=shift,
    )


@router.get("/personas", response_model=list[PersonaOut])
async def list_personas(facilities: FacilitiesDep) -> list[PersonaOut]:
    """The demo people a visitor can sign in as, each with their role."""
    names = {f.profile.key: f.profile.name for f in await facilities.list_facilities()}
    return [
        PersonaOut(
            id=persona.id,
            display_name=persona.display_name,
            initials=persona.initials,
            role=persona.role,
            facility_key=persona.facility_key,
            facility_name=names[persona.facility_key] if persona.facility_key else None,
        )
        for persona in DEMO_PERSONAS
    ]


@router.post("/session", status_code=201, response_model=SessionOut, responses=problems(404, 422))
async def start_session(
    body: SessionIn,
    request: Request,
    response: Response,
    clock: ClockDep,
    users: UsersDep,
    sessions: SessionsDep,
    facilities: FacilitiesDep,
) -> SessionOut:
    """Signs in as a demo persona and sets the session cookie."""
    user = await users.get_user(body.persona_id)
    now = clock.now()
    shift = None
    if user.facility_key is not None:
        profile = (await facilities.get_facility(user.facility_key)).profile
        shift = default_shift(now, profile)
    token = await sessions.create(user.id, shift, now)
    settings: Settings = request.app.state.settings
    response.set_cookie(
        COOKIE,
        token,
        max_age=int(SESSION_LIFETIME.total_seconds()),
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.app_env in {"demo", "prod"},
    )
    return session_out(user, shift)


@router.get("/session", response_model=SessionOut, responses=problems(401), dependencies=SIGNED_IN)
async def get_session(signed_in: SignedInDep) -> SessionOut:
    return session_out(signed_in.user, signed_in.session.shift)


@router.delete("/session", status_code=204, dependencies=SIGNED_IN)
async def end_session(
    token: Annotated[str | None, Security(SESSION_COOKIE)],
    response: Response,
    sessions: SessionsDep,
) -> None:
    # Not a docstring: that would become the route's description and change the frozen openapi.json.
    # Signing out is 204 with or without a session, and the cookie is cleared either way.
    if token is not None:
        await sessions.delete(token)
    response.delete_cookie(COOKIE, path="/", httponly=True, samesite="lax")


@router.put(
    "/session/shift",
    response_model=SessionOut,
    responses=problems(401, 403, 422),
    dependencies=SIGNED_IN,
)
async def change_shift(
    body: ShiftChoiceIn,
    nurse: NurseDep,
    clock: ClockDep,
    sessions: SessionsDep,
    facilities: FacilitiesDep,
) -> SessionOut | Response:
    """A nurse switches her session to the previous, current or next shift."""
    profile = (await facilities.get_facility(nurse.facility_key)).profile
    chosen = next(
        (
            shift
            for shift in shift_choices(clock.now(), profile)
            if shift.starts_at == body.starts_at
        ),
        None,
    )
    if chosen is None:
        return problem_response(
            422,
            "invalid_request",
            "see errors",
            errors=[
                FieldError(
                    field="body.starts_at",
                    message="must be the start of the previous, current or next shift",
                )
            ],
        )
    await sessions.set_shift(nurse.token, chosen)
    return session_out(nurse.user, chosen)
