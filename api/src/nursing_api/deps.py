"""FastAPI dependencies: they read what `create_app`'s lifespan put on `app.state`."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request, Security
from nursing_core.domain.errors import Forbidden, NotFound
from nursing_core.domain.patient import PatientRecord
from nursing_core.domain.shifts import ShiftRef
from nursing_core.domain.users import can_edit_settings, can_see_facility, can_write_notes
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

from nursing_api.problems import NotSignedIn
from nursing_api.routes import SESSION_COOKIE
from nursing_api.worker import InProcessQueue


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


def get_queue(request: Request) -> InProcessQueue:
    queue: InProcessQueue = request.app.state.queue
    return queue


ClockDep = Annotated[Clock, Depends(get_clock)]
UsersDep = Annotated[PgUserRepository, Depends(get_users)]
SessionsDep = Annotated[PgSessionRepository, Depends(get_sessions)]
FacilitiesDep = Annotated[PgFacilityRepository, Depends(get_facilities)]
PatientsDep = Annotated[PgPatientRepository, Depends(get_patients)]
NotesDep = Annotated[PgNoteRepository, Depends(get_notes)]
QueueDep = Annotated[InProcessQueue, Depends(get_queue)]


@dataclass(frozen=True)
class SignedIn:
    """Who is signed in: the person, their live session, and the cookie's token."""

    user: StoredUser
    session: StoredSession
    token: str


async def current_session(
    token: Annotated[str | None, Security(SESSION_COOKIE)],
    clock: ClockDep,
    sessions: SessionsDep,
    users: UsersDep,
) -> SignedIn:
    """The signed-in person, or `NotSignedIn` (401) when the cookie is missing or has expired."""
    if token is None:
        raise NotSignedIn
    session = await sessions.get(token, clock.now())
    if session is None:
        raise NotSignedIn
    return SignedIn(user=await users.get_user(session.user_id), session=session, token=token)


SignedInDep = Annotated[SignedIn, Depends(current_session)]


@dataclass(frozen=True)
class Nurse:
    """A signed-in nurse: who she is, her facility, and the shift her session is working."""

    user: StoredUser
    facility_key: str
    shift: ShiftRef
    token: str


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
