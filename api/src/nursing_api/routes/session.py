from datetime import datetime

from fastapi import APIRouter, Request, Response
from nursing_core.auth.pins import PinRefused, check_new_pin, hash_pin
from nursing_core.demo import DEMO_FACILITY_NAMES, DEMO_PERSONAS
from nursing_core.domain.errors import NotFound
from nursing_core.domain.shifts import default_shift, shift_choices
from nursing_core.domain.users import SessionGate
from nursing_core.storage.repositories import (
    SESSION_LIFETIME,
    PgFacilityRepository,
    PgSessionRepository,
    StoredSession,
    StoredUser,
)
from starlette.concurrency import run_in_threadpool

from nursing_api.auth.pin_check import SessionEnded, prove_pin, session_ended_response
from nursing_api.deps import (
    ClockDep,
    FacilitiesDep,
    GatedSessionDep,
    MaybeSessionDep,
    NurseDep,
    SessionsDep,
    SignedIn,
    UsersDep,
    gate_of,
)
from nursing_api.problems import (
    FieldError,
    NotSignedIn,
    PinAlreadySet,
    SessionGated,
    problem_response,
    problems,
)
from nursing_api.routes import CSRF, SIGNED_IN
from nursing_api.schemas import PersonaOut, PinIn, SessionIn, SessionOut, ShiftChoiceIn
from nursing_api.settings import Settings

router = APIRouter(prefix="/api/v1", tags=["session"])

COOKIE = "sl_session"


def session_out(
    user: StoredUser, session: StoredSession, gate: SessionGate, settings: Settings
) -> SessionOut:
    return SessionOut(
        user_id=user.id,
        display_name=user.display_name,
        initials=user.initials,
        role=user.role,
        facility_key=user.facility_key,
        shift=session.shift,
        kind="persona" if user.persona else "google",
        gate=gate,
        csrf_token=session.csrf_token,
        expires_at=session.expires_at,
        idle_lock_seconds=settings.idle_lock_minutes * 60,
    )


async def begin_session(
    user: StoredUser,
    *,
    now: datetime,
    settings: Settings,
    sessions: PgSessionRepository,
    facilities: PgFacilityRepository,
    response: Response,
) -> StoredSession:
    """Starts `user`'s session and sets its cookie on `response` (persona and Google sign-in).

    The shift is the facility's current one and the length its `session_max_hours`; the admin has
    no shift and 12 hours. The cookie lasts exactly as long as the session.
    """
    shift = None
    max_hours = int(SESSION_LIFETIME.total_seconds() // 3600)  # the admin's
    if user.facility_key is not None:
        profile = (await facilities.get_facility(user.facility_key)).profile
        shift = default_shift(now, profile)
        max_hours = profile.session_max_hours
    token = (await sessions.create(user.id, shift, now, max_hours)).token
    session = await sessions.get(token, now)
    if session is None:  # just created: only a clock that jumped could lose it
        raise NotSignedIn
    response.set_cookie(
        COOKIE,
        token,
        max_age=int((session.expires_at - now).total_seconds()),
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.app_env in {"demo", "prod"},
    )
    return session


def ensure_personas_offered(request: Request) -> None:
    """The demo personas exist everywhere but `prod`, where they answer 404 like unknown ones."""
    settings: Settings = request.app.state.settings
    if settings.app_env == "prod":
        raise NotFound("no such persona")


@router.get("/personas", response_model=list[PersonaOut], responses=problems(404))
async def list_personas(request: Request) -> list[PersonaOut]:
    """The demo people a visitor can sign in as, each with their role."""
    ensure_personas_offered(request)
    return [
        PersonaOut(
            id=persona.id,
            display_name=persona.display_name,
            initials=persona.initials,
            role=persona.role,
            facility_key=persona.facility_key,
            facility_name=DEMO_FACILITY_NAMES[persona.facility_key]
            if persona.facility_key
            else None,
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
    ensure_personas_offered(request)
    user = await users.get_user(body.persona_id)
    if not user.persona:
        # An invited person signs in with Google only: their id opens nothing here, and looks
        # like an unknown one.
        raise NotFound("no such persona")
    now = clock.now()
    settings: Settings = request.app.state.settings
    # The first visitor of a new nursing day finds the demo's settings back at their presets.
    await facilities.reset_stale_to_presets(now)
    session = await begin_session(
        user,
        now=now,
        settings=settings,
        sessions=sessions,
        facilities=facilities,
        response=response,
    )
    return session_out(user, session, gate_of(user, session, now, settings), settings)


@router.get("/session", response_model=SessionOut, responses=problems(401), dependencies=SIGNED_IN)
async def get_session(signed_in: GatedSessionDep, request: Request) -> SessionOut:
    return session_out(
        signed_in.user, signed_in.session, signed_in.gate, request.app.state.settings
    )


@router.delete(
    "/session", status_code=204, responses=problems(403), dependencies=[*SIGNED_IN, *CSRF]
)
async def end_session(
    signed_in: MaybeSessionDep,
    response: Response,
    sessions: SessionsDep,
) -> None:
    # Not a docstring: that would become the route's description and change the frozen openapi.json.
    # Signing out is 204 with or without a session, and the cookie is cleared either way.
    if signed_in is not None:
        await sessions.delete(signed_in.token)
    response.delete_cookie(COOKIE, path="/", httponly=True, samesite="lax")


async def open_answer(
    signed_in: SignedIn, request: Request, users: UsersDep, sessions: SessionsDep, now: datetime
) -> SessionOut:
    """The session as it stands after its PIN was proved: re-read, so the gate is the real one."""
    session = await sessions.get(signed_in.token, now)
    if session is None:  # ended in the meantime
        raise NotSignedIn
    user = await users.get_user(signed_in.user.id)
    settings: Settings = request.app.state.settings
    return session_out(user, session, gate_of(user, session, now, settings), settings)


@router.post(
    "/session/pin",
    response_model=SessionOut,
    responses=problems(401, 403, 409, 422),
    dependencies=[*SIGNED_IN, *CSRF],
)
async def set_pin(
    body: PinIn,
    request: Request,
    signed_in: GatedSessionDep,
    clock: ClockDep,
    users: UsersDep,
    sessions: SessionsDep,
) -> SessionOut | Response:
    """After the first Google sign-in: choose a six-digit PIN (409 when one is already set)."""
    if signed_in.gate is not SessionGate.SET_PIN:
        raise PinAlreadySet
    try:
        check_new_pin(body.pin)
    except PinRefused as refused:
        message = "a PIN is six digits" if refused.reason == "format" else "that PIN is too easy"
        return problem_response(
            422,
            "invalid_request",
            "see errors",
            errors=[FieldError(field="body.pin", message=message)],
        )
    pin_hash = await run_in_threadpool(hash_pin, body.pin)
    if not await users.set_pin(signed_in.user.id, pin_hash):  # another request set one first
        raise PinAlreadySet
    now = clock.now()
    await sessions.mark_pin_verified(signed_in.token, now)
    return await open_answer(signed_in, request, users, sessions, now)


@router.post(
    "/session/unlock",
    response_model=SessionOut,
    responses=problems(401, 403, 409, 422, 423),
    dependencies=[*SIGNED_IN, *CSRF],
)
async def unlock(
    body: PinIn,
    request: Request,
    signed_in: GatedSessionDep,
    clock: ClockDep,
    users: UsersDep,
    sessions: SessionsDep,
) -> SessionOut | Response:
    """The PIN after a sign-in or the idle lock. A wrong one is 403 with the tries left."""
    if signed_in.gate in {SessionGate.SET_PIN, SessionGate.PIN_LOCKED}:
        raise SessionGated(signed_in.gate)
    try:
        await prove_pin(signed_in, body.pin, users=users, sessions=sessions, clock=clock)
    except SessionEnded:
        return session_ended_response()
    now = clock.now()
    await sessions.mark_pin_verified(signed_in.token, now)
    return await open_answer(signed_in, request, users, sessions, now)


@router.put(
    "/session/shift",
    response_model=SessionOut,
    responses=problems(401, 403, 422, 423),
    dependencies=[*SIGNED_IN, *CSRF],
)
async def change_shift(
    body: ShiftChoiceIn,
    request: Request,
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
    session = await sessions.get(nurse.token, clock.now())
    if session is None:
        raise NotSignedIn
    settings: Settings = request.app.state.settings
    return session_out(
        nurse.user, session, gate_of(nurse.user, session, clock.now(), settings), settings
    )
