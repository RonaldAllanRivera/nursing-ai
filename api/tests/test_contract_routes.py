"""The P1 endpoints: declared and frozen in openapi.json."""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from nursing_api.app import create_app
from nursing_api.settings import Settings
from nursing_core.domain.facility import preset

PATIENT = "00000000-0000-4000-8000-000000000011"
JOB = "00000000-0000-4000-8000-000000000014"
NOTE = "00000000-0000-4000-8000-000000000015"
SETTINGS_BODY = preset("PH", "ph-demo", "SYNTHETIC").model_dump(mode="json", exclude={"key"})
IF_MATCH = {"If-Match": '"v1"'}

# (method, path, body, headers, success status, declared problem statuses)
ROUTES: list[tuple[str, str, Any, dict[str, str], int, set[int]]] = [
    ("GET", "/api/v1/facilities", None, {}, 200, {401}),
    ("GET", "/api/v1/facilities/ph-demo", None, {}, 200, {401, 403, 404, 422}),
    (
        "PUT",
        "/api/v1/facilities/ph-demo",
        SETTINGS_BODY,
        {"If-Match": '"f1"'},
        200,
        {401, 403, 404, 412, 422, 428},
    ),
    ("GET", "/api/v1/personas", None, {}, 200, set()),
    ("POST", "/api/v1/session", {"persona_id": PATIENT}, {}, 201, {404, 422}),
    ("GET", "/api/v1/session", None, {}, 200, {401}),
    ("DELETE", "/api/v1/session", None, {}, 204, set()),
    (
        "PUT",
        "/api/v1/session/shift",
        {"starts_at": "2026-11-12T14:00:00+08:00"},
        {},
        200,
        {401, 403, 422},
    ),
    ("GET", "/api/v1/patients", None, {}, 200, {401, 403}),
    ("GET", f"/api/v1/patients/{PATIENT}", None, {}, 200, {401, 403, 404, 422}),
    (
        "POST",
        f"/api/v1/patients/{PATIENT}/rough-notes",
        {"text": "pt still weak"},
        {"Idempotency-Key": "k-1"},
        202,
        {401, 403, 404, 422, 428},
    ),
    ("GET", f"/api/v1/draft-jobs/{JOB}", None, {}, 200, {401, 403, 404, 422}),
    ("GET", f"/api/v1/notes/{NOTE}", None, {}, 200, {401, 403, 404, 422}),
    (
        "PATCH",
        f"/api/v1/notes/{NOTE}/lines/e1-D2",
        {"action": "confirm"},
        IF_MATCH,
        200,
        {401, 403, 404, 409, 412, 422, 428},
    ),
    (
        "POST",
        f"/api/v1/notes/{NOTE}/sign",
        None,
        IF_MATCH,
        200,
        {401, 403, 404, 409, 412, 422, 428},
    ),
    (
        "POST",
        f"/api/v1/notes/{NOTE}/discard",
        None,
        IF_MATCH,
        200,
        {401, 403, 404, 409, 412, 422, 428},
    ),
]
TEMPLATES = {
    f"/api/v1/patients/{PATIENT}": "/api/v1/patients/{patient_id}",
    f"/api/v1/patients/{PATIENT}/rough-notes": "/api/v1/patients/{patient_id}/rough-notes",
    f"/api/v1/draft-jobs/{JOB}": "/api/v1/draft-jobs/{job_id}",
    f"/api/v1/notes/{NOTE}": "/api/v1/notes/{note_id}",
    f"/api/v1/notes/{NOTE}/lines/e1-D2": "/api/v1/notes/{note_id}/lines/{line_id}",
    f"/api/v1/notes/{NOTE}/sign": "/api/v1/notes/{note_id}/sign",
    f"/api/v1/notes/{NOTE}/discard": "/api/v1/notes/{note_id}/discard",
    "/api/v1/facilities/ph-demo": "/api/v1/facilities/{facility_key}",
}


def app() -> FastAPI:
    return create_app(Settings(database_url="postgresql+asyncpg://unused@localhost/unused"))


def operation(spec: dict[str, Any], method: str, path: str) -> dict[str, Any]:
    template = TEMPLATES.get(path, path)
    found: dict[str, Any] = spec["paths"][template][method.lower()]
    return found


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    application = app()
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            yield http


@pytest.mark.parametrize(("method", "path", "_body", "_headers", "ok", "problems"), ROUTES)
def test_every_route_declares_its_problem_responses(
    method: str, path: str, _body: Any, _headers: dict[str, str], ok: int, problems: set[int]
) -> None:
    declared = {int(code) for code in operation(app().openapi(), method, path)["responses"]}
    assert declared == {ok} | problems


def test_no_route_is_left_undeclared() -> None:
    spec = app().openapi()
    declared = {
        (method.upper(), path)
        for path, item in spec["paths"].items()
        for method in item
        if path != "/api/v1/health"
    }
    assert declared == {(m, TEMPLATES.get(p, p)) for m, p, *_ in ROUTES}


def test_no_default_validation_error_schema() -> None:
    schemas = app().openapi()["components"]["schemas"]
    assert "HTTPValidationError" not in schemas
    assert "ValidationError" not in schemas


def test_problem_responses_are_problem_json() -> None:
    for path, item in app().openapi()["paths"].items():
        for method, op in item.items():
            for code, response in op["responses"].items():
                if int(code) >= 400:
                    assert set(response["content"]) == {"application/problem+json"}, (path, method)


def test_success_headers_are_declared() -> None:
    spec = app().openapi()
    note = operation(spec, "GET", f"/api/v1/notes/{NOTE}")["responses"]["200"]
    assert "ETag" in note["headers"]
    posted = operation(spec, "POST", f"/api/v1/patients/{PATIENT}/rough-notes")["responses"]
    assert "Location" in posted["202"]["headers"]
    facility = operation(spec, "PUT", "/api/v1/facilities/ph-demo")["responses"]["200"]
    assert "ETag" in facility["headers"]


def test_no_schema_is_split_into_input_and_output() -> None:
    schemas = app().openapi()["components"]["schemas"]
    assert not [name for name in schemas if name.endswith(("-Input", "-Output"))]


SIGNED_IN = {
    (method, TEMPLATES.get(path, path))
    for method, path, *_ in ROUTES
    if (method, path) not in {("GET", "/api/v1/personas"), ("POST", "/api/v1/session")}
}


def test_session_cookie_is_declared_where_a_session_is_needed() -> None:
    spec = app().openapi()
    scheme = spec["components"]["securitySchemes"]["session"]
    assert scheme == {"type": "apiKey", "in": "cookie", "name": "sl_session"} | {
        k: v for k, v in scheme.items() if k == "description"
    }
    for path, item in spec["paths"].items():
        for method, op in item.items():
            needs = (method.upper(), path) in SIGNED_IN
            assert (op.get("security") == [{"session": []}]) is needs, (method, path)


@pytest.mark.asyncio
async def test_unknown_field_is_never_echoed(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/session",
        json={"persona_id": PATIENT, "Qorvex Dramblin fever 39": 1},
    )
    assert response.status_code == 422
    assert "Qorvex" not in response.text
    assert response.json()["errors"] == [{"field": "body", "message": "unknown field"}]
