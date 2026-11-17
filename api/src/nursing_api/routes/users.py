from uuid import UUID

import structlog
from fastapi import APIRouter, Response
from nursing_core.domain.errors import Forbidden, NotFound
from nursing_core.domain.users import can_list_staff, can_manage_staff, can_reset_pin
from nursing_core.storage.repositories import StoredUser

from nursing_api.auth.pin_check import SessionEnded, prove_pin, session_ended_response
from nursing_api.deps import ClockDep, FacilitiesDep, SessionsDep, SignedInDep, UsersDep
from nursing_api.problems import FieldError, problem_response, problems
from nursing_api.routes import CSRF, SIGNED_IN
from nursing_api.schemas import InviteIn, PinIn, UserOut

router = APIRouter(prefix="/api/v1/users", tags=["staff"], dependencies=SIGNED_IN)

log = structlog.get_logger("nursing_api.routes.users")


def user_out(user: StoredUser) -> UserOut:
    return UserOut(
        id=user.id,
        # Only a persona has no email, and personas are never listed or acted on.
        email=user.email or "",
        display_name=user.display_name,
        initials=user.initials,
        role=user.role,
        facility_key=user.facility_key,
        status=user.status,
        pin_locked=user.pin_locked,
    )


async def visible_target(actor: StoredUser, user_id: UUID, users: UsersDep) -> StoredUser:
    """The person `user_id` names, or `NotFound` (404) when the actor can't see them: a persona,
    another facility's person for a head nurse, or an unknown id."""
    target = await users.get_user(user_id)
    if target.persona or (
        actor.facility_key is not None and target.facility_key != actor.facility_key
    ):
        raise NotFound("no such person")
    return target


@router.get("", response_model=list[UserOut], responses=problems(401, 403, 423))
async def list_staff(signed_in: SignedInDep, users: UsersDep) -> list[UserOut]:
    """Everyone invited, for the admin; a head nurse's own facility. Personas aren't listed."""
    actor = signed_in.user
    if not can_list_staff(actor.role, persona=actor.persona):
        raise Forbidden("not yours to list")
    # The admin has no facility: None lists everyone.
    return [user_out(user) for user in await users.list_staff(actor.facility_key)]


@router.post(
    "",
    status_code=201,
    response_model=UserOut,
    responses=problems(401, 403, 409, 422, 423),
    dependencies=CSRF,
)
async def invite(
    body: InviteIn,
    signed_in: SignedInDep,
    users: UsersDep,
    sessions: SessionsDep,
    clock: ClockDep,
    facilities: FacilitiesDep,
) -> UserOut | Response:
    """The admin invites a Google account by email, with a role and a facility."""
    actor = signed_in.user
    if not can_manage_staff(actor.role, persona=actor.persona):
        raise Forbidden("only the admin invites")
    # Checked before the PIN: no PIN is compared here, so no guess goes uncounted.
    if body.facility_key is not None:
        try:
            await facilities.get_facility(body.facility_key)
        except NotFound:
            return problem_response(
                422,
                "invalid_request",
                "see errors",
                errors=[FieldError(field="body.facility_key", message="no such facility")],
            )
    try:
        await prove_pin(signed_in, body.pin, users=users, sessions=sessions, clock=clock)
    except SessionEnded:
        return session_ended_response()
    invited = await users.invite(body.email, body.role, body.facility_key, actor.id)
    return user_out(invited)


@router.post(
    "/{user_id}/revoke",
    response_model=UserOut,
    responses=problems(401, 403, 404, 422, 423),
    dependencies=CSRF,
)
async def revoke(
    user_id: UUID,
    body: PinIn,
    signed_in: SignedInDep,
    users: UsersDep,
    sessions: SessionsDep,
    clock: ClockDep,
) -> UserOut | Response:
    """The admin ends someone's access and sessions; the row stays for their signed notes."""
    actor = signed_in.user
    if not can_manage_staff(actor.role, persona=actor.persona):
        raise Forbidden("only the admin revokes")
    target = await visible_target(actor, user_id, users)
    if target.id == actor.id:
        raise Forbidden("the admin cannot revoke themselves")
    try:
        await prove_pin(signed_in, body.pin, users=users, sessions=sessions, clock=clock)
    except SessionEnded:
        return session_ended_response()
    return user_out(await users.revoke(target.id, clock.now()))


@router.post(
    "/{user_id}/pin-reset",
    response_model=UserOut,
    responses=problems(401, 403, 404, 422, 423),
    dependencies=CSRF,
)
async def reset_pin(
    user_id: UUID,
    body: PinIn,
    signed_in: SignedInDep,
    users: UsersDep,
    sessions: SessionsDep,
    clock: ClockDep,
) -> UserOut | Response:
    """In person: the admin, or a head nurse for her facility's nurses, clears a locked PIN."""
    actor = signed_in.user
    if not can_list_staff(actor.role, persona=actor.persona):
        raise Forbidden("not yours to reset")
    target = await visible_target(actor, user_id, users)
    allowed = can_reset_pin(
        actor_role=actor.role,
        actor_facility=actor.facility_key,
        actor_id=actor.id,
        actor_persona=actor.persona,
        target_role=target.role,
        target_facility=target.facility_key,
        target_id=target.id,
        target_persona=target.persona,
    )
    if not allowed:
        raise Forbidden("cannot reset this PIN")
    try:
        await prove_pin(signed_in, body.pin, users=users, sessions=sessions, clock=clock)
    except SessionEnded:
        return session_ended_response()
    reset = await users.reset_pin(target.id)
    log.warning("security.pin_reset", user_id=str(target.id), by_user_id=str(actor.id))
    return user_out(reset)
