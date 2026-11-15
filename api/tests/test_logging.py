"""Logs are JSON lines with an allowlist of keys, a request id, and never any text of the record."""

import json
import logging
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from nursing_api.logging import ALLOWED_KEYS
from nursing_core.db import create_engine, ping
from nursing_core.demo import load_demo_cases

from .helpers import PH_STAFF, STAFF_NURSE, forbidden_words, sign_in
from .test_problems import throwaway_app


def json_lines(text: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for line in text.splitlines():
        if line.startswith("{"):
            found.append(json.loads(line))
    return found


@pytest.mark.asyncio
async def test_a_request_is_logged_with_its_id_and_the_response_carries_it(
    client: httpx.AsyncClient, capfd: pytest.CaptureFixture[str]
) -> None:
    response = await client.get("/api/v1/personas", headers={"X-Request-ID": "chosen-by-caller"})
    out = capfd.readouterr().out
    request_id = response.headers["x-request-id"]
    assert request_id != "chosen-by-caller"
    lines = [line for line in json_lines(out) if line.get("event") == "request"]
    assert len(lines) == 1
    line = lines[0]
    assert line["request_id"] == request_id
    assert line["method"] == "GET"
    assert line["route"] == "/api/v1/personas"
    assert line["status"] == 200
    assert line["duration_ms"] >= 0
    assert set(line) <= ALLOWED_KEYS


@pytest.mark.asyncio
async def test_each_request_gets_its_own_id(client: httpx.AsyncClient) -> None:
    first = await client.get("/api/v1/personas")
    second = await client.get("/api/v1/personas")
    assert first.headers["x-request-id"] != second.headers["x-request-id"]


@pytest.mark.asyncio
async def test_the_route_is_the_template_never_the_raw_path(
    client: httpx.AsyncClient, capfd: pytest.CaptureFixture[str]
) -> None:
    await sign_in(client, PH_STAFF)
    capfd.readouterr()
    await client.get("/api/v1/patients/not-a-uuid-zebracanary")
    await client.get("/nowhere/zebracanary")
    lines = [line for line in json_lines(capfd.readouterr().out) if line.get("event") == "request"]
    assert [line["route"] for line in lines] == ["/api/v1/patients/{patient_id}", "unmatched"]
    assert [line["status"] for line in lines] == [422, 404]


@pytest.mark.asyncio
async def test_an_unexpected_error_is_logged_by_class_only(
    capfd: pytest.CaptureFixture[str],
) -> None:
    transport = httpx.ASGITransport(app=throwaway_app(), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/throwaway/boom")
    captured = capfd.readouterr()
    assert response.status_code == 500
    assert "zebracanary" not in captured.out + captured.err
    request = [line for line in json_lines(captured.out) if line.get("event") == "request"]
    assert request[0]["status"] == 500
    assert request[0]["error_class"] == "RuntimeError"


@pytest.mark.asyncio
async def test_stdlib_loggers_pass_the_same_allowlist(
    free_port: int, capfd: pytest.CaptureFixture[str], app: FastAPI
) -> None:
    del app  # creating the app configures logging
    engine = create_engine(f"postgresql+asyncpg://app:x@127.0.0.1:{free_port}/app")
    try:
        assert await ping(engine, 1.0) is False
    finally:
        await engine.dispose()
    lines = [
        line
        for line in json_lines(capfd.readouterr().out)
        if line.get("event") == "database ping failed"
    ]
    assert len(lines) == 1
    assert lines[0]["error_class"]
    assert set(lines[0]) <= ALLOWED_KEYS


@pytest.mark.asyncio
async def test_logs_never_contain_note_text_or_names(
    app: FastAPI,
    client: httpx.AsyncClient,
    caplog: pytest.LogCaptureFixture,
    capfd: pytest.CaptureFixture[str],
) -> None:
    del app
    for name in ("", "nursing_api", "nursing_core", "uvicorn", "fastapi", "starlette"):
        logging.getLogger(name).setLevel(logging.DEBUG)
    caplog.set_level(logging.DEBUG)
    cases = load_demo_cases()
    assert {case.facility_key for case in cases} == {"ph-demo", "us-demo"}
    for case in cases:
        await sign_in(client, STAFF_NURSE[case.facility_key])
        session = await client.get("/api/v1/session")
        shift = session.json()["shift"]
        choice = {"starts_at": shift["starts_at"]}
        assert (await client.put("/api/v1/session/shift", json=choice)).status_code == 200
        far = {"starts_at": "2030-01-01T00:00:00Z"}
        assert (await client.put("/api/v1/session/shift", json=far)).status_code == 422
        assert (await client.delete("/api/v1/session")).status_code == 204
        unknown = await client.post("/api/v1/session", json={"persona_id": str(uuid4())})
        assert unknown.status_code == 404
    captured = capfd.readouterr()
    everything = (caplog.text + captured.out + captured.err).lower()
    assert "request" in captured.out  # something was logged, so the check below means something
    assert caplog.records
    for case in cases:
        for word in forbidden_words(case):
            assert word not in everything, f"{case.key} leaked a forbidden string"
