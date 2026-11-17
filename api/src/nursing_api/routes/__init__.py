"""The P1 and P2 endpoints; openapi.json freezes their paths, bodies and problem statuses."""

from typing import Any

from fastapi import Security
from fastapi.security import APIKeyCookie, APIKeyHeader

# The session cookie, declared once so openapi.json names it on every route that needs a
# session. Code that reads the session must go through this object (Security(SESSION_COOKIE)), or
# the frozen openapi.json changes.
SESSION_COOKIE = APIKeyCookie(
    name="sl_session",
    scheme_name="session",
    description="The session cookie set by POST /api/v1/session",
    auto_error=False,
)
# The CSRF token from the session's answer (`SessionOut.csrf_token`), required on every POST, PUT,
# PATCH and DELETE that has a session. Read it through this object, as with the cookie.
CSRF_HEADER = APIKeyHeader(
    name="X-CSRF-Token",
    scheme_name="csrf",
    description="The csrf_token from the session's answer; required on every change",
    auto_error=False,
)
SIGNED_IN = [Security(SESSION_COOKIE)]
# Added to a route that changes something; its router (or the route) also declares SIGNED_IN.
CSRF = [Security(CSRF_HEADER)]


def etag_header(
    description: str = "The version, for If-Match on the next change",
) -> dict[str, Any]:
    return {"ETag": {"description": description, "schema": {"type": "string"}}}


def location_header(description: str) -> dict[str, Any]:
    return {"Location": {"description": description, "schema": {"type": "string"}}}
