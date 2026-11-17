"""FastAPI dependencies: they read what `create_app`'s lifespan put on `app.state`."""

import hmac
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Annotated

import structlog
from fastapi import Depends, Request, Security
from nursing_core.auth.gate import session_gate
from nursing_core.domain.errors import Forbidden, NotFound
from nursing_core.domain.patient import PatientRecord
from nursing_core.domain.shifts import ShiftRef
from nursing_core.domain.users import (
    SessionGate,
    UserStatus,
    can_edit_settings,
    can_see_facility,
    can_write_notes,
)
from nursing_core.ports import Clock
from nursing_core.storage.repositories import (
    PgFacilityRepository,
    PgNoteRepository,
    PgPatientRepository,
    PgSessionRepository,
    PgUserRepository,
    StoredSession,
    StoredUser,
)

from nursing_api.problems import CsrfFailed, NotSignedIn, SessionGated
from nursing_api.queue import ManagedQueue
from nursing_api.routes import CSRF_HEADER, SESSION_COOKIE
from nursing_api.settings import Settings

log = structlog.get_logger("nursing_api.deps")

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# The web polls this route while a draft is written; a poll is not the nurse being at the screen,
# so it never counts as activity. Spotted by route template: jobs.py is not ours to change.
DRAFT_JOB_POLL = ("GET", "/api/v1/draft-jobs/{job_id}")


def get_clock(request: Request) -> Clock:
    clock: Clock = request.app.state.clock
    return clock


def get_users(request: Request) -> PgUserRepository:
    users: PgUserRepository = request.app.state.users
    return users


def get_sessions(request: Request) -> PgSessionRepository:
    sessions: PgSessionRepository = request.app.state.sessions
    return sessions


def get_facilities(request: Request) -> PgFacilityRepository:
    facilities: PgFacilityRepository = request.app.state.facilities
    return facilities


def get_patients(request: Request) -> PgPatientRepository:
    patients: PgPatientRepository = request.app.state.patients
    return patients


def get_notes(request: Request) -> PgNoteRepository:
    notes: PgNoteRepository = request.app.state.notes
    return notes


def get_queue(request: Request) -> ManagedQueue:
    queue: ManagedQueue = request.app.state.queue
    return queue


ClockDep = Annotated[Clock, Depends(get_clock)]
UsersDep = Annotated[PgUserRepository, Depends(get_users)]
SessionsDep = Annotated[PgSessionRepository, Depends(get_sessions)]
FacilitiesDep = Annotated[PgFacilityRepository, Depends(get_facilities)]
PatientsDep = Annotated[PgPatientRepository, Depends(get_patients)]
NotesDep = Annotated[PgNoteRepository, Depends(get_notes)]
QueueDep = Annotated[ManagedQueue, Depends(get_queue)]


@dataclass(frozen=True)
class SignedIn:
    """Who is signed in: the person, their live session, its gate now, and the cookie's token."""

    user: StoredUser
    session: StoredSession
    gate: SessionGate
    token: str = field(repr=False)  # the raw cookie value: never in a repr or a log


def gate_of(
    user: StoredUser, session: StoredSession, now: datetime, settings: Settings
) -> SessionGate:
    """What this session may do at `now` (the pure rule, fed the stored facts)."""
    return session_gate(
        has_pin=user.has_pin,
        pin_locked=user.pin_locked,
        pin_verified_at=session.pin_verified_at,
        last_active_at=session.last_active_at,
        now=now,
        idle_lock=timedelta(minutes=settings.idle_lock_minutes),
    )


def _is_draft_job_poll(request: Request) -> bool:
    route = request.scope.get("route")
    return (request.method, getattr(route, "path", None)) == DRAFT_JOB_POLL


async def current_session(
    request: Request,
    token: Annotated[str | None, Security(SESSION_COOKIE)],
    clock: ClockDep,
    sessions: SessionsDep,
    users: UsersDep,
) -> SignedIn:
    """The signed-in person at any gate: the routes that work while locked use this.

    Refuses in this order: 401 (no cookie, an unknown or expired session, a revoked user), then
    403 `csrf_failed` for a POST, PUT, PATCH or DELETE without this session's token. An open
    session is marked active, except by the draft-job poll.
    """
    if token is None:
        raise NotSignedIn
    now = clock.now()
    session = await sessions.get(token, now)
    if session is None:
        raise NotSignedIn
    user = await users.get_user(session.user_id)
    if user.status is UserStatus.REVOKED:
        raise NotSignedIn
    if request.method in UNSAFE_METHODS:
        # Read from the request, never `Security(CSRF_HEADER)`: that would add the header to
        # every signed-in GET in openapi.json.
        sent = request.headers.get(CSRF_HEADER.model.name, "")
        if not hmac.compare_digest(sent.encode(), session.csrf_token.encode()):
            log.warning("security.csrf_failed", user_id=str(user.id))
            raise CsrfFailed
    settings: Settings = request.app.state.settings
    gate = gate_of(user, session, now, settings)
    if gate is SessionGate.OPEN and not _is_draft_job_poll(request):
        await sessions.touch(token, now)
    return SignedIn(user=user, session=session, gate=gate, token=token)


GatedSessionDep = Annotated[SignedIn, Depends(current_session)]


async def current_open_session(gated: GatedSessionDep) -> SignedIn:
    """The signed-in person with an open session: every data route; `SessionGated` (423) else."""
    if gated.gate is not SessionGate.OPEN:
        raise SessionGated(gated.gate)
    return gated


SignedInDep = Annotated[SignedIn, Depends(current_open_session)]


async def optional_session(
    request: Request,
    token: Annotated[str | None, Security(SESSION_COOKIE)],
    clock: ClockDep,
    sessions: SessionsDep,
    users: UsersDep,
) -> SignedIn | None:
    """The session at any gate, or None when there is none (signing out still answers 204)."""
    try:
        return await current_session(request, token, clock, sessions, users)
    except NotSignedIn:
        return None


MaybeSessionDep = Annotated[SignedIn | None, Depends(optional_session)]


@dataclass(frozen=True)
class Nurse:
    """A signed-in nurse: who she is, her facility, and the shift her session is working."""

    user: StoredUser
    facility_key: str
    shift: ShiftRef
    token: str = field(repr=False)


async def require_nurse(signed_in: SignedInDep) -> Nurse:
    """The signed-in nurse; `Forbidden` (403) for the admin, who doesn't chart.

    Used as a dependency, so the 403 comes before the request body is checked.
    """
    user = signed_in.user
    shift = signed_in.session.shift
    if not can_write_notes(user.role) or user.facility_key is None or shift is None:
        raise Forbidden("only a nurse works a shift")
    return Nurse(user=user, facility_key=user.facility_key, shift=shift, token=signed_in.token)


NurseDep = Annotated[Nurse, Depends(require_nurse)]


async def require_admin(signed_in: SignedInDep) -> StoredUser:
    """The signed-in admin; `Forbidden` (403) for a nurse. A dependency: 403 beats body checks."""
    if not can_edit_settings(signed_in.user.role):
        raise Forbidden("only the admin edits settings")
    return signed_in.user


AdminDep = Annotated[StoredUser, Depends(require_admin)]


def ensure_own_facility(nurse: Nurse, patient: PatientRecord) -> None:
    """A patient of another facility looks like no patient at all (404): ids are opaque."""
    if not can_see_facility(nurse.user.role, nurse.facility_key, patient.summary.facility_key):
        raise NotFound("no such patient")
