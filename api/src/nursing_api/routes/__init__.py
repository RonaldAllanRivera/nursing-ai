"""The P1 endpoints. Each answers 501 until its lane fills it in; openapi.json freezes them."""

from typing import Any, NoReturn

from fastapi import Security
from fastapi.security import APIKeyCookie

from nursing_api.problems import NotImplementedRoute

# The session cookie, declared once so openapi.json names it on every route that needs a
# session. Code that reads the session must go through this object (Security(SESSION_COOKIE)), or
# the frozen openapi.json changes.
SESSION_COOKIE = APIKeyCookie(
    name="sl_session",
    scheme_name="session",
    description="The session cookie set by POST /api/v1/session",
    auto_error=False,
)
SIGNED_IN = [Security(SESSION_COOKIE)]


def not_built() -> NoReturn:
    raise NotImplementedRoute


def etag_header(
    description: str = "The version, for If-Match on the next change",
) -> dict[str, Any]:
    return {"ETag": {"description": description, "schema": {"type": "string"}}}
