from typing import Self
from uuid import uuid4

from fastapi import APIRouter, Request, Response
from nursing_core.auth.pins import hash_pin
from nursing_core.domain.errors import NotFound
from nursing_core.domain.users import Role
from nursing_core.storage import tables
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import insert, select

from nursing_api.deps import ClockDep, FacilitiesDep, SessionsDep, UsersDep, gate_of
from nursing_api.routes.session import begin_session, session_out
from nursing_api.schemas import Pin, SessionOut
from nursing_api.settings import Settings

# Registered only when APP_ENV=test, and never in openapi.json: the e2e harness's way to sign in a
# throwaway e2e-<uuid>@example.com Google user without Google.
router = APIRouter(prefix="/api/v1/test", include_in_schema=False)

E2E_EMAIL = "e2e-%@example.com"


class TestSessionIn(BaseModel):
    """Local to this hidden route, so not part of the frozen schemas."""

    __test__ = False  # not a pytest class

    model_config = ConfigDict(extra="forbid")

    role: Role
    facility_key: str | None
    pin: Pin | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def _admin_alone_has_no_facility(self) -> Self:
        if (self.facility_key is None) != (self.role is Role.ADMIN):
            raise ValueError("an admin has no facility, and every nurse has one")
        return self


@router.post("/session", status_code=201, response_model=SessionOut)
async def start_test_session(
    body: TestSessionIn,
    request: Request,
    response: Response,
    clock: ClockDep,
    users: UsersDep,
    sessions: SessionsDep,
    facilities: FacilitiesDep,
) -> SessionOut:
    # Not a docstring: the route is hidden, and a test harness is its only reader.
    # A new active Google-kind user, as a real sign-in leaves one: the gate is `set_pin` without a
    # PIN and `enter_pin` with one.
    key = uuid4()
    email = f"e2e-{key}@example.com"
    engine = request.app.state.engine
    async with engine.begin() as conn:
        facility_id = None
        if body.facility_key is not None:
            facility_id = await conn.scalar(
                select(tables.facility.c.id).where(tables.facility.c.key == body.facility_key)
            )
            if facility_id is None:
                raise NotFound("no such facility")
        await conn.execute(
            insert(tables.app_user).values(
                id=key,
                display_name="E2E Tester",
                initials="ET",
                role=body.role.value,
                facility_id=facility_id,
                email=email,
                google_sub=f"e2e-{key}",
                pin_hash=None if body.pin is None else hash_pin(body.pin),
            )
        )
    user = await users.get_user(key)
    now = clock.now()
    settings: Settings = request.app.state.settings
    session = await begin_session(
        user,
        now=now,
        settings=settings,
        sessions=sessions,
        facilities=facilities,
        response=response,
    )
    return session_out(user, session, gate_of(user, session, now, settings), settings)


@router.post("/teardown", status_code=204)
async def teardown_test_users(request: Request, clock: ClockDep, users: UsersDep) -> None:
    # Revokes every unrevoked e2e user (ending their sessions); a row is never deleted.
    async with request.app.state.engine.begin() as conn:
        ids = (
            await conn.scalars(
                select(tables.app_user.c.id).where(
                    tables.app_user.c.email.like(E2E_EMAIL),
                    tables.app_user.c.revoked_at.is_(None),
                )
            )
        ).all()
    for user_id in ids:
        await users.revoke(user_id, clock.now())
