"""FastAPI dependencies: they read what `create_app`'s lifespan put on `app.state`."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request, Security
from nursing_core.ports import Clock
from nursing_core.storage.repositories import (
    PgFacilityRepository,
    PgSessionRepository,
    PgUserRepository,
    StoredSession,
    StoredUser,
)

from nursing_api.problems import NotSignedIn
from nursing_api.routes import SESSION_COOKIE


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


ClockDep = Annotated[Clock, Depends(get_clock)]
UsersDep = Annotated[PgUserRepository, Depends(get_users)]
SessionsDep = Annotated[PgSessionRepository, Depends(get_sessions)]
FacilitiesDep = Annotated[PgFacilityRepository, Depends(get_facilities)]


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
