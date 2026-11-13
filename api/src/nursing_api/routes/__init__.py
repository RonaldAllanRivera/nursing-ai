"""The P1 endpoints. Each answers 501 until its lane fills it in; openapi.json freezes them."""

from typing import Any, NoReturn

from nursing_api.problems import NotImplementedRoute


def not_built() -> NoReturn:
    raise NotImplementedRoute


def etag_header(
    description: str = "The version, for If-Match on the next change",
) -> dict[str, Any]:
    return {"ETag": {"description": description, "schema": {"type": "string"}}}
