import base64
import hashlib
import hmac
import secrets
from datetime import datetime
from typing import Literal

import structlog
from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse
from nursing_core.domain.errors import IdentityMismatch, NotFound
from nursing_core.domain.users import UserStatus
from nursing_core.storage.repositories import (
    PgFacilityRepository,
    PgSessionRepository,
    PgUserRepository,
)

from nursing_api.auth import oauth_cookie
from nursing_api.auth.oauth_cookie import OAuthAttempt
from nursing_api.auth.oidc import GoogleIdentity, GoogleOidc
from nursing_api.auth.session_cookie import secure_cookies
from nursing_api.deps import ClockDep, FacilitiesDep, SessionsDep, UsersDep
from nursing_api.problems import problems
from nursing_api.routes import location_header
from nursing_api.routes.session import begin_session
from nursing_api.schemas import SignInError
from nursing_api.settings import Settings

router = APIRouter(prefix="/api/v1/auth/google", tags=["session"])
log = structlog.get_logger("nursing_api.auth.google")

CALLBACK_PATH = "/api/v1/auth/google/callback"
Reason = Literal[
    "state_mismatch",
    "token_invalid",
    "email_unverified",
    "no_access",
    "revoked",
    "identity_mismatch",
]


def _challenge(verifier: str) -> str:
    """RFC 7636's S256: base64url(sha256(verifier)) without padding."""
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _google(request: Request) -> tuple[GoogleOidc, Settings]:
    """The Google client and settings, or 404 while Google sign-in is off."""
    google: GoogleOidc | None = request.app.state.google
    settings: Settings = request.app.state.settings
    if google is None or not settings.google_sign_in:
        raise NotFound("Google sign-in is off")
    return google, settings


def _secret(settings: Settings) -> str:
    if settings.google_client_secret is None:  # google_sign_in is on, so never
        raise NotFound("Google sign-in is off")
    return settings.google_client_secret.get_secret_value()


def _initials(name: str) -> str:
    words = name.split()
    first, last = words[0][0], words[-1][0]
    return (first if len(words) == 1 else first + last).upper()


def _refuse(
    settings: Settings,
    error: SignInError,
    reason: Reason | None,
    user_id: object | None = None,
    error_class: str | None = None,
) -> Response:
    """Back to the sign-in page with a reason, no session, and the attempt's cookie gone.

    The log line holds a fixed reason word and, when we know her, the user's id: never an email,
    a `sub`, a code, a state or a token. `error_class` is the failure's class name only.
    """
    if reason is not None:
        details = {} if user_id is None else {"user_id": str(user_id)}
        if error_class is not None:
            details["error_class"] = error_class
        log.warning("security.sign_in_refused", reason=reason, **details)
    return _finish(settings, f"{settings.site_url}/sign-in?error={error}")


def _finish(settings: Settings, location: str) -> RedirectResponse:
    response = RedirectResponse(location, status_code=302)
    response.delete_cookie(
        oauth_cookie.NAME,
        path=oauth_cookie.PATH,
        httponly=True,
        samesite="lax",
        secure=secure_cookies(settings),
    )
    return response


@router.get(
    "/start",
    status_code=302,
    response_class=RedirectResponse,
    responses={302: {"headers": location_header("Google's account chooser")}, **problems(404)},
)
async def google_start(request: Request, clock: ClockDep) -> Response:
    """Sends the browser to Google (404 when Google sign-in is off). Reads no database."""
    google, settings = _google(request)
    attempt = OAuthAttempt(
        state=secrets.token_urlsafe(32),
        nonce=secrets.token_urlsafe(32),
        verifier=secrets.token_urlsafe(48),  # 64 characters, inside RFC 7636's 43 to 128
        issued_at=clock.now(),
    )
    response = RedirectResponse(
        google.authorization_url(
            state=attempt.state,
            nonce=attempt.nonce,
            code_challenge=_challenge(attempt.verifier),
            redirect_uri=f"{settings.site_url}{CALLBACK_PATH}",
        ),
        status_code=302,
    )
    response.set_cookie(
        oauth_cookie.NAME,
        oauth_cookie.seal(attempt, secret=_secret(settings)),
        max_age=int(oauth_cookie.LIFETIME.total_seconds()),
        path=oauth_cookie.PATH,
        httponly=True,
        samesite="lax",
        secure=secure_cookies(settings),
    )
    return response


# Google's answer arrives as query parameters (code, state, or error), read from the request:
# declared ones would add a 422 that no browser can act on. Every refusal redirects instead.
@router.get(
    "/callback",
    status_code=302,
    response_class=RedirectResponse,
    responses={
        302: {
            "description": (
                "To the app, or to /sign-in?error=no_access, /sign-in?error=expired or "
                "/sign-in?error=cancelled (SignInError in schemas.py)"
            ),
            "headers": location_header("The app, or the sign-in page with ?error="),
        }
    },
)
async def google_callback(
    request: Request,
    clock: ClockDep,
    users: UsersDep,
    sessions: SessionsDep,
    facilities: FacilitiesDep,
) -> Response:
    """Google's redirect back: an invited person gets a session; anyone else, a reason."""
    google, settings = _google(request)
    query = request.query_params
    if query.get("error") is not None:
        return _refuse(settings, "cancelled", None)
    now = clock.now()
    attempt = oauth_cookie.open_seal(
        request.cookies.get(oauth_cookie.NAME), secret=_secret(settings), now=now
    )
    state = query.get("state")
    if (
        attempt is None
        or state is None
        or not hmac.compare_digest(attempt.state.encode(), state.encode())
    ):
        return _refuse(settings, "expired", "state_mismatch")
    code = query.get("code")
    if not code:
        return _refuse(settings, "expired", "token_invalid")
    try:
        id_token = await google.exchange(
            code=code,
            code_verifier=attempt.verifier,
            redirect_uri=f"{settings.site_url}{CALLBACK_PATH}",
        )
        identity = await google.verify_id_token(id_token, nonce=attempt.nonce)
    except Exception as error:  # a refused code, a bad token or an unreachable Google
        # She tries again; the log says what kind of failure it was (never its message).
        return _refuse(settings, "expired", "token_invalid", error_class=type(error).__name__)
    if not identity.email_verified:
        return _refuse(settings, "no_access", "email_unverified")
    return await _sign_in(identity, settings, now, users, sessions, facilities)


async def _sign_in(
    identity: GoogleIdentity,
    settings: Settings,
    now: datetime,
    users: PgUserRepository,
    sessions: PgSessionRepository,
    facilities: PgFacilityRepository,
) -> Response:
    """The verified person against the invite list: a session for her, or a reason."""
    email = identity.email.strip().lower()
    if email == settings.bootstrap_admin_email:
        await users.ensure_bootstrap_admin(email)
    user = await users.get_user_by_email(email)
    if user is None:
        return _refuse(settings, "no_access", "no_access")
    if user.status is UserStatus.REVOKED:
        return _refuse(settings, "no_access", "revoked", user.id)
    name = (identity.name or "").strip() or email.partition("@")[0]
    try:
        user = await users.bind_google(user.id, identity.sub, name, _initials(name))
    except IdentityMismatch:
        return _refuse(settings, "no_access", "identity_mismatch", user.id)
    response = _finish(settings, f"{settings.site_url}/")
    await begin_session(
        user,
        now=now,
        settings=settings,
        sessions=sessions,
        facilities=facilities,
        response=response,
    )
    return response
