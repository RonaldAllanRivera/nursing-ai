"""The P1 and P2 endpoints: declared and frozen in openapi.json."""

from collections.abc import AsyncIterator
from typing import Any, get_args

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from nursing_api.app import create_app
from nursing_api.schemas import FacilityUpdateIn, InviteIn, PinIn, SignInError
from nursing_api.settings import Settings
from nursing_core.demo import DEMO_PIN
from nursing_core.domain.facility import FacilitySettings, preset
from nursing_core.domain.users import Role
from pydantic import ValidationError

PATIENT = "00000000-0000-4000-8000-000000000011"
JOB = "00000000-0000-4000-8000-000000000014"
NOTE = "00000000-0000-4000-8000-000000000015"
ROUGH = "00000000-0000-4000-8000-000000000013"
USER = "00000000-0000-4000-8000-000000000101"
SETTINGS_BODY = preset("PH", "ph-demo", "SYNTHETIC").model_dump(mode="json", exclude={"key"})
PIN = {"pin": DEMO_PIN}
INVITE = {"email": "nurse.b@example.com", "role": "staff_nurse", "facility_key": "ph-demo"} | PIN
IF_MATCH = {"If-Match": '"v1"'}

# (method, path, body, headers, success status, declared problem statuses)
ROUTES: list[tuple[str, str, Any, dict[str, str], int, set[int]]] = [
    ("GET", "/api/v1/facilities", None, {}, 200, {401, 423}),
    ("GET", "/api/v1/facilities/ph-demo", None, {}, 200, {401, 403, 404, 422, 423}),
    (
        "PUT",
        "/api/v1/facilities/ph-demo",
        SETTINGS_BODY | PIN,
        {"If-Match": '"f1"'},
        200,
        {401, 403, 404, 412, 422, 423, 428},
    ),
    (
        "POST",
        "/api/v1/facilities/ph-demo/reset",
        PIN,
        {"If-Match": '"f1"'},
        200,
        {401, 403, 404, 412, 422, 423, 428},
    ),
    ("GET", "/api/v1/sign-in-options", None, {}, 200, set()),
    ("GET", "/api/v1/personas", None, {}, 200, {404}),
    ("GET", "/api/v1/auth/google/start", None, {}, 302, {404}),
    ("GET", "/api/v1/auth/google/callback", None, {}, 302, set()),
    ("POST", "/api/v1/session", {"persona_id": PATIENT}, {}, 201, {404, 422}),
    ("GET", "/api/v1/session", None, {}, 200, {401}),
    ("DELETE", "/api/v1/session", None, {}, 204, {403}),
    ("POST", "/api/v1/session/pin", PIN, {}, 200, {401, 403, 409, 422}),
    ("POST", "/api/v1/session/unlock", PIN, {}, 200, {401, 403, 409, 422, 423}),
    (
        "PUT",
        "/api/v1/session/shift",
        {"starts_at": "2026-11-12T14:00:00+08:00"},
        {},
        200,
        {401, 403, 422, 423},
    ),
    ("GET", "/api/v1/users", None, {}, 200, {401, 403, 423}),
    ("POST", "/api/v1/users", INVITE, {}, 201, {401, 403, 409, 422, 423}),
    ("POST", f"/api/v1/users/{USER}/revoke", PIN, {}, 200, {401, 403, 404, 422, 423}),
    ("POST", f"/api/v1/users/{USER}/pin-reset", PIN, {}, 200, {401, 403, 404, 422, 423}),
    ("GET", "/api/v1/patients", None, {}, 200, {401, 403, 423}),
    ("GET", f"/api/v1/patients/{PATIENT}", None, {}, 200, {401, 403, 404, 422, 423}),
    (
        "POST",
        f"/api/v1/patients/{PATIENT}/rough-notes",
        {"text": "pt still weak"},
        {"Idempotency-Key": "k-1"},
        202,
        {401, 403, 404, 422, 423, 428, 429},
    ),
    (
        "POST",
        f"/api/v1/rough-notes/{ROUGH}/draft-jobs",
        None,
        {},
        202,
        {401, 403, 404, 409, 422, 423, 429},
    ),
    ("GET", f"/api/v1/draft-jobs/{JOB}", None, {}, 200, {401, 403, 404, 422, 423}),
    ("GET", f"/api/v1/notes/{NOTE}", None, {}, 200, {401, 403, 404, 422, 423}),
    (
        "PATCH",
        f"/api/v1/notes/{NOTE}/lines/e1-D2",
        {"action": "confirm"},
        IF_MATCH,
        200,
        {401, 403, 404, 409, 412, 422, 423, 428},
    ),
    (
        "POST",
        f"/api/v1/notes/{NOTE}/sign",
        PIN,
        IF_MATCH,
        200,
        {401, 403, 404, 409, 412, 422, 423, 428},
    ),
    (
        "POST",
        f"/api/v1/notes/{NOTE}/discard",
        None,
        IF_MATCH,
        200,
        {401, 403, 404, 409, 412, 422, 423, 428},
    ),
]
# The routes the lanes build; until then each answers 501 (the stub isn't declared, so filling it
# in never changes openapi.json).
NEW_ROUTES = {
    ("GET", "/api/v1/sign-in-options"),
    ("GET", "/api/v1/auth/google/start"),
    ("GET", "/api/v1/auth/google/callback"),
    ("POST", "/api/v1/session/pin"),
    ("POST", "/api/v1/session/unlock"),
    ("POST", "/api/v1/facilities/ph-demo/reset"),
    ("GET", "/api/v1/users"),
    ("POST", "/api/v1/users"),
    ("POST", f"/api/v1/users/{USER}/revoke"),
    ("POST", f"/api/v1/users/{USER}/pin-reset"),
    ("POST", f"/api/v1/rough-notes/{ROUGH}/draft-jobs"),
}
# Hidden from openapi.json: the e2e harness's sign-in and the SQS worker's and ops' events.
HIDDEN: list[tuple[str, str, dict[str, Any]]] = [
    ("POST", "/api/v1/test/session", {}),
    ("POST", "/events", {"Records": []}),
]
TEMPLATES = {
    f"/api/v1/users/{USER}/revoke": "/api/v1/users/{user_id}/revoke",
    f"/api/v1/users/{USER}/pin-reset": "/api/v1/users/{user_id}/pin-reset",
    f"/api/v1/rough-notes/{ROUGH}/draft-jobs": "/api/v1/rough-notes/{rough_note_id}/draft-jobs",
    "/api/v1/facilities/ph-demo/reset": "/api/v1/facilities/{facility_key}/reset",
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
    # A test-env worker, so the hidden routes (the test sign-in, /events) are registered too.
    return create_app(
        Settings(
            database_url="postgresql+asyncpg://unused@localhost/unused",
            app_env="test",
            app_role="worker",
        )
    )


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


SIGNED_OUT = {
    ("GET", "/api/v1/sign-in-options"),
    ("GET", "/api/v1/personas"),
    ("GET", "/api/v1/auth/google/start"),
    ("GET", "/api/v1/auth/google/callback"),
    ("POST", "/api/v1/session"),
}
SIGNED_IN = {(method, TEMPLATES.get(path, path)) for method, path, *_ in ROUTES} - SIGNED_OUT
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
# Reading the session, setting the first PIN and signing out work at any gate.
ANY_GATE = {
    ("GET", "/api/v1/session"),
    ("DELETE", "/api/v1/session"),
    ("POST", "/api/v1/session/pin"),
}


def security_of(op: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = op.get("security", [])
    return found


def test_session_cookie_is_declared_where_a_session_is_needed() -> None:
    spec = app().openapi()
    scheme = spec["components"]["securitySchemes"]["session"]
    assert scheme == {"type": "apiKey", "in": "cookie", "name": "sl_session"} | {
        k: v for k, v in scheme.items() if k == "description"
    }
    for path, item in spec["paths"].items():
        for method, op in item.items():
            needs = (method.upper(), path) in SIGNED_IN
            assert ({"session": []} in security_of(op)) is needs, (method, path)


def test_every_unsafe_signed_in_route_declares_the_csrf_header() -> None:
    spec = app().openapi()
    scheme = spec["components"]["securitySchemes"]["csrf"]
    assert {k: v for k, v in scheme.items() if k != "description"} == {
        "type": "apiKey",
        "in": "header",
        "name": "X-CSRF-Token",
    }
    for path, item in spec["paths"].items():
        for method, op in item.items():
            needs = (method.upper(), path) in SIGNED_IN and method.upper() in UNSAFE
            assert ({"csrf": []} in security_of(op)) is needs, (method, path)
            if needs:
                assert "403" in op["responses"], (method, path)


def test_every_signed_in_route_declares_423() -> None:
    spec = app().openapi()
    for method, path in SIGNED_IN - ANY_GATE:
        assert "423" in spec["paths"][path][method.lower()]["responses"], (method, path)
    for method, path in ANY_GATE:
        assert "423" not in spec["paths"][path][method.lower()]["responses"], (method, path)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "body", "headers"),
    [(m, p, b, h) for m, p, b, h, *_ in ROUTES if (m, p) in NEW_ROUTES]
    + [(m, p, b, {}) for m, p, b in HIDDEN],
)
async def test_new_routes_answer_501_until_built(
    client: httpx.AsyncClient, method: str, path: str, body: Any, headers: dict[str, str]
) -> None:
    response = await client.request(method, path, json=body, headers=headers)
    # Registered: never a 404 or 405. A stub answers 501; a built route answers anything else,
    # so this stays true while the lanes build them.
    assert response.status_code not in (404, 405), response.text
    if response.status_code == 501:
        assert response.json()["code"] == "not_implemented"


def test_hidden_routes_are_not_in_openapi() -> None:
    paths = app().openapi()["paths"]
    for _method, path, _body in HIDDEN:
        assert path not in paths


def test_contract_schemas_carry_the_p2_fields() -> None:
    schemas = app().openapi()["components"]["schemas"]
    session = schemas["SessionOut"]
    assert {"kind", "gate", "csrf_token", "expires_at", "idle_lock_seconds"} <= set(
        session["required"]
    )
    assert "retryable" in schemas["DraftJobOut"]["required"]
    assert "demo_note" in schemas["PatientDetail"]["required"]
    assert "tries_left" in schemas["Problem"]["properties"]
    assert schemas["PinIn"]["properties"]["pin"]["pattern"] == "^[0-9]{6}$"
    assert set(schemas["SignInOptionsOut"]["required"]) == {
        "google",
        "personas",
        "demo",
        "demo_pin",
    }
    assert {"status", "pin_locked", "email"} <= set(schemas["UserOut"]["required"])
    for code in ("set_pin", "enter_pin", "idle_locked", "pin_locked", "csrf_failed", "pin_wrong"):
        assert code in schemas["Problem"]["properties"]["code"]["enum"]


@pytest.mark.parametrize(
    "pin", ["12345", "1234567", "12a456", "\uff11\uff12\uff13\uff14\uff15\uff16"]
)
def test_a_pin_is_six_ascii_digits_at_the_door(pin: str) -> None:
    # The schema every PIN body uses (the routes check the session first, so test it here).
    with pytest.raises(ValidationError) as refused:
        PinIn.model_validate({"pin": pin})
    assert refused.value.errors()[0]["loc"] == ("pin",)
    assert pin not in str(refused.value)
    assert PinIn.model_validate({"pin": DEMO_PIN}).pin == DEMO_PIN


def test_saving_settings_never_keeps_the_pin() -> None:
    body = FacilityUpdateIn.model_validate(SETTINGS_BODY | PIN)
    settings = body.settings()
    assert type(settings) is FacilitySettings
    assert "pin" not in settings.model_dump()
    assert DEMO_PIN not in repr(body)


def test_an_invite_is_lowercased_and_only_the_admin_has_no_facility() -> None:
    invite = InviteIn.model_validate(INVITE | {"email": "  Nurse.B@Example.COM "})
    assert invite.email == "nurse.b@example.com"
    InviteIn.model_validate(INVITE | {"role": "admin", "facility_key": None})
    for wrong in (
        {"role": "admin"},
        {"facility_key": None},
        {"email": "nobody"},
        {"email": "a@b@example.com"},
    ):
        with pytest.raises(ValidationError):
            InviteIn.model_validate(INVITE | wrong)
    assert InviteIn.model_validate(INVITE).role is Role.STAFF_NURSE


@pytest.mark.asyncio
async def test_unknown_field_is_never_echoed(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/session",
        json={"persona_id": PATIENT, "Qorvex Dramblin fever 39": 1},
    )
    assert response.status_code == 422
    assert "Qorvex" not in response.text
    assert response.json()["errors"] == [{"field": "body", "message": "unknown field"}]


def test_the_callbacks_sign_in_errors_are_frozen() -> None:
    # The auth lane redirects with these and the web lane shows a message for each.
    assert set(get_args(SignInError)) == {"no_access", "expired", "cancelled"}
    paths = app().openapi()["paths"]
    redirect = paths["/api/v1/auth/google/callback"]["get"]["responses"]["302"]
    for value in get_args(SignInError):
        assert f"error={value}" in redirect["description"]
