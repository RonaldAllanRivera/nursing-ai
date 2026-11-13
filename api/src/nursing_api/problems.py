"""RFC 9457 problem responses: one shape for every error, documented as application/problem+json.

Errors never echo the request: a validation error says which field, not what was typed, because
a request body can hold note text.
"""

from typing import Any, Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

PROBLEM_JSON = "application/problem+json"

ProblemCode = Literal[
    "not_signed_in",
    "forbidden",
    "not_found",
    "note_locked",
    "review_incomplete",
    "stale_version",
    "precondition_required",
    "idempotency_key_reused",
    "invalid_request",
    "not_implemented",
]

TITLES: dict[int, str] = {
    401: "Not signed in",
    403: "Not allowed",
    404: "Not found",
    409: "Conflict",
    412: "The note or setting has changed",
    422: "The request isn't valid",
    428: "A required header is missing",
    501: "Not built yet",
}


class Problem(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    code: ProblemCode
    line_ids: list[str] | None = None


class NotImplementedRoute(Exception):
    """A declared route that a lane hasn't filled in yet."""


def problem_response(
    status: int, code: ProblemCode, detail: str | None = None, line_ids: list[str] | None = None
) -> JSONResponse:
    body = Problem(
        title=TITLES.get(status, "Error"),
        status=status,
        detail=detail,
        code=code,
        line_ids=line_ids,
    )
    return JSONResponse(
        body.model_dump(mode="json", exclude_none=True), status_code=status, media_type=PROBLEM_JSON
    )


def problems(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """The `responses=` entry declaring a route's problem statuses."""
    return {status: {"model": Problem, "description": TITLES[status]} for status in statuses}


async def _not_implemented(_request: Request, _exc: Exception) -> JSONResponse:
    return problem_response(501, "not_implemented")


async def _invalid(_request: Request, exc: Exception) -> JSONResponse:
    fields: list[str] = []
    if isinstance(exc, RequestValidationError):
        for error in exc.errors():
            location = ".".join(str(part) for part in error.get("loc", ()))
            if location and location not in fields:
                fields.append(location)
    detail = f"check: {', '.join(fields)}" if fields else None
    return problem_response(422, "invalid_request", detail)


def install_problems(app: FastAPI) -> None:
    """Problem handlers, and an OpenAPI document whose errors are application/problem+json."""
    app.add_exception_handler(NotImplementedRoute, _not_implemented)
    app.add_exception_handler(RequestValidationError, _invalid)
    plain_openapi = app.openapi

    def problem_openapi() -> dict[str, Any]:
        if app.openapi_schema is not None:
            return app.openapi_schema
        spec = plain_openapi()
        for item in spec.get("paths", {}).values():
            for operation in item.values():
                for code, response in operation.get("responses", {}).items():
                    content = response.get("content", {})
                    if int(code) >= 400 and "application/json" in content:
                        content[PROBLEM_JSON] = content.pop("application/json")
        app.openapi_schema = spec
        return spec

    app.openapi = problem_openapi  # type: ignore[method-assign]
