"""Proving the PIN: the one check unlock, signing and every settings save share.

The check is claim-first: it takes one of the five tries before it verifies anything, so a burst
of parallel guesses can never verify more than five PINs, and a right guess that races the fifth
wrong one cannot unlock a locked account. Hashing runs off the event loop (Argon2 costs real
memory and CPU). Nothing here logs or raises with a PIN or a hash in it.
"""

import structlog
from fastapi import Response
from nursing_core.auth.pins import verify_pin
from nursing_core.domain.users import SessionGate
from nursing_core.ports import Clock
from nursing_core.storage.repositories import PgSessionRepository, PgUserRepository
from starlette.concurrency import run_in_threadpool

from nursing_api.auth.session_cookie import clear_session_cookie
from nursing_api.deps import SignedIn
from nursing_api.problems import NotSignedIn, PinWrong, SessionGated, problem_response

log = structlog.get_logger("nursing_api.auth.pin_check")


class SessionEnded(NotSignedIn):
    """A demo persona's fifth wrong PIN: the session is gone. The route answers 401 and clears
    the cookie (`session_ended_response`)."""


def session_ended_response() -> Response:
    """401 `not_signed_in` with the session cookie cleared."""
    response = problem_response(401, "not_signed_in")
    clear_session_cookie(response)
    return response


async def prove_pin(
    signed_in: SignedIn,
    pin: str,
    *,
    users: PgUserRepository,
    sessions: PgSessionRepository,
    clock: Clock,
) -> None:
    """Returns when `pin` is this person's PIN; otherwise raises.

    - `PinWrong` (403) with the tries left;
    - `SessionGated(PIN_LOCKED)` (423) when the account's tries are used up (the fifth wrong
      PIN locks a Google user's PIN and logs `security.pin_locked` once);
    - `SessionEnded` (401) for a persona: her tries count per session, and the fifth ends
      that session only.
    A right PIN clears the failures (the user's, or the persona's session's).
    """
    user = signed_in.user
    if user.persona:
        left = await sessions.claim_session_pin_try(signed_in.token)
    else:
        left = await users.claim_pin_try(user.id)
    if left is None:
        if user.persona:
            # The session is already gone or swapped for a fresh one by a proof that won the race:
            # a plain 401, which must not clear the fresh cookie that proof just set.
            await sessions.delete(signed_in.token)
            raise NotSignedIn
        # The tries are used up: make sure the lock is real (a request that claimed the fifth
        # try may have died before it locked), and log it only if this call locked it.
        if await users.lock_pin(user.id, clock.now()):
            log.warning("security.pin_locked", user_id=str(user.id))
        raise SessionGated(SessionGate.PIN_LOCKED)

    stored = await users.pin_hash(user.id)
    right = stored is not None and await run_in_threadpool(verify_pin, stored, pin)
    if right:
        if user.persona:
            cleared = await sessions.clear_session_pin_failures(signed_in.token)
        else:
            cleared = await users.clear_pin_failures(user.id)
        if not cleared:  # the fifth wrong guess got there first
            if user.persona:  # the session ended or was swapped meanwhile: a plain 401
                raise NotSignedIn
            raise SessionGated(SessionGate.PIN_LOCKED)
        return

    if left == 0:
        if user.persona:
            await sessions.delete(signed_in.token)  # her row never changes: this session ends
            raise SessionEnded
        if await users.lock_pin(user.id, clock.now()):
            log.warning("security.pin_locked", user_id=str(user.id))
        raise SessionGated(SessionGate.PIN_LOCKED)
    log.warning("security.pin_failed", user_id=str(user.id), tries_left=left)
    raise PinWrong(left)
