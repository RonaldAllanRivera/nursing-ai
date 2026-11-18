"""The session cookie: the one place that sets it and clears it.

Its name is the one `SESSION_COOKIE` declares (routes/__init__.py), the object every route reads
it through. It is httpOnly (no script reads it), SameSite=Lax, on every path, Secure where the
site is served over HTTPS (the demo and prod), and it lasts exactly as long as its session.
"""

from datetime import datetime

from fastapi import Response

from nursing_api.routes import SESSION_COOKIE
from nursing_api.settings import Settings

NAME = SESSION_COOKIE.model.name


def secure_cookies(settings: Settings) -> bool:
    """Our cookies (the session's and the Google sign-in attempt's) are Secure in the demo and
    prod, which are served over HTTPS only."""
    return settings.app_env in {"demo", "prod"}


def set_session_cookie(
    response: Response, token: str, *, expires_at: datetime, now: datetime, settings: Settings
) -> None:
    """Gives the browser `token` until the session's `expires_at` (a new session, or a new
    token for the same session once its PIN is proved)."""
    response.set_cookie(
        NAME,
        token,
        max_age=int((expires_at - now).total_seconds()),
        path="/",
        httponly=True,
        samesite="lax",
        secure=secure_cookies(settings),
    )


def clear_session_cookie(response: Response) -> None:
    """Tells the browser to forget the session cookie (signing out, or a session that ended)."""
    response.delete_cookie(NAME, path="/", httponly=True, samesite="lax")
