"""RFC 9457 problem responses: one shape for every error, documented as application/problem+json.

Errors never echo the request: a validation error names the field and the rule, never what was
typed or an unknown key, because a request body can hold note text or a name.
"""

from collections.abc import Awaitable, Callable
from typing import Any, Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from nursing_core.domain.errors import (
    Forbidden,
    IdempotencyConflict,
    NoteLocked,
    NotFound,
    ReviewIncomplete,
    StaleVersion,
)
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
    "not_implemented",  # no route answers it now; it stays because openapi.json names it
]

TITLES: dict[int, str] = {
    401: "Not signed in",
    403: "Not allowed",
    404: "Not found",
    409: "Conflict",
    412: "The note or setting has changed",
    422: "The request isn't valid",
    428: "A required header is missing",
}


class FieldError(BaseModel):
    field: str  # a dotted path such as "body.text"; "body" for a rule about the whole form
    message: str


class Problem(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    code: ProblemCode
    line_ids: list[str] | None = None
    errors: list[FieldError] | None = None


# Pydantic error types whose messages describe the rule, never the input. Every other type gets
# a plain "invalid value" (some messages quote part of the input, such as a bad UUID's character).
_SAFE_MESSAGES = frozenset(
    {
        "value_error",
        "missing",
        "string_too_long",
        "string_too_short",
        "string_type",
        "literal_error",
        "enum",
        "too_short",
        "too_long",
        "greater_than",
        "greater_than_equal",
        "less_than",
        "less_than_equal",
        "int_type",
        "bool_type",
        "list_type",
        "dict_type",
        "model_type",
        "model_attributes_type",
        "union_tag_invalid",
        "union_tag_not_found",
        "timezone_aware",
        "time_type",
        "datetime_type",
    }
)


class NotSignedIn(Exception):
    """No session cookie, or one that names no live session."""


class PreconditionRequired(Exception):
    """A header the change needs (If-Match or Idempotency-Key) is missing."""


class ActionRefused(Exception):
    """A line action that breaks a rule (answered 422). The message states the rule, never text."""


def problem_response(
    status: int,
    code: ProblemCode,
    detail: str | None = None,
    line_ids: list[str] | None = None,
    errors: list[FieldError] | None = None,
) -> JSONResponse:
    body = Problem(
        title=TITLES.get(status, "Error"),
        status=status,
        detail=detail,
        code=code,
        line_ids=line_ids,
        errors=errors,
    )
    return JSONResponse(
        body.model_dump(mode="json", exclude_none=True), status_code=status, media_type=PROBLEM_JSON
    )


def problems(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """The `responses=` entry declaring a route's problem statuses."""
    return {status: {"model": Problem, "description": TITLES[status]} for status in statuses}


def field_errors(exc: RequestValidationError) -> list[FieldError]:
    found: list[FieldError] = []
    for error in exc.errors():
        kind = str(error.get("type", ""))
        location = [str(part) for part in error.get("loc", ())]
        if kind == "extra_forbidden":
            # The last part is the unknown key itself, which could be anything the caller typed.
            location, message = location[:-1], "unknown field"
        elif kind in _SAFE_MESSAGES:
            message = str(error.get("msg", "invalid value")).removeprefix("Value error, ")
        else:
            message = "invalid value"
        item = FieldError(field=".".join(location) or "body", message=message)
        if item not in found:
            found.append(item)
    return found


async def _invalid(_request: Request, exc: Exception) -> JSONResponse:
    errors = field_errors(exc) if isinstance(exc, RequestValidationError) else []
    return problem_response(422, "invalid_request", "see errors", errors=errors or None)


async def _action_refused(_request: Request, exc: Exception) -> JSONResponse:
    message = str(exc)
    return problem_response(
        422,
        "invalid_request",
        "see errors",
        errors=[FieldError(field="body.action", message=message)],
    )


# Each domain error and the problem it becomes. A problem never carries the error's message.
_SIMPLE: dict[type[Exception], tuple[int, ProblemCode]] = {
    NotSignedIn: (401, "not_signed_in"),
    Forbidden: (403, "forbidden"),
    NotFound: (404, "not_found"),
    NoteLocked: (409, "note_locked"),
    StaleVersion: (412, "stale_version"),
    IdempotencyConflict: (422, "idempotency_key_reused"),
    PreconditionRequired: (428, "precondition_required"),
}


def _simple_handler(
    status: int, code: ProblemCode
) -> Callable[[Request, Exception], Awaitable[JSONResponse]]:
    async def handle(_request: Request, _exc: Exception) -> JSONResponse:
        return problem_response(status, code)

    return handle


async def _review_incomplete(_request: Request, exc: Exception) -> JSONResponse:
    lines = exc.line_ids if isinstance(exc, ReviewIncomplete) else []
    return problem_response(409, "review_incomplete", line_ids=lines)


def install_problems(app: FastAPI) -> None:
    """Problem handlers, and an OpenAPI document whose errors are application/problem+json."""
    for error, (status, code) in _SIMPLE.items():
        app.add_exception_handler(error, _simple_handler(status, code))
    app.add_exception_handler(ReviewIncomplete, _review_incomplete)
    app.add_exception_handler(RequestValidationError, _invalid)
    app.add_exception_handler(ActionRefused, _action_refused)
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
