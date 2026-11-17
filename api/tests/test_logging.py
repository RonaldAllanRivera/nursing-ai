"""Logs are JSON lines with an allowlist of keys, a request id, and never any text of the record."""

import asyncio
import gc
import json
import logging
import logging.config
from typing import Any
from uuid import uuid4

import httpx
import pytest
import structlog
from fastapi import FastAPI
from nursing_api.app import create_app
from nursing_api.logging import ALLOWED_KEYS, LIBRARY_EVENT, QUIET_LOGGERS, configure_logging
from nursing_core.db import create_engine, ping
from nursing_core.demo import DEMO_PIN, DemoCase, load_demo_cases

from .helpers import (
    PH_STAFF,
    STAFF_NURSE,
    drain,
    forbidden_words,
    leaked,
    post_note,
    sign_in,
)
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


def edit_text(case: DemoCase) -> str:
    """The text of the nurse's edit: a stretch of her own rough note, which `leaked` looks for."""
    return case.rough_note.text[:30]


async def review_and_sign(client: httpx.AsyncClient, note_id: str, text: str) -> None:
    """Edit one line to `text`, confirm what still needs her, then sign."""
    path = f"/api/v1/notes/{note_id}"
    note = (await client.get(path)).json()
    lines = [
        line
        for entry in note["draft"]["entries"]
        for line in [entry["focus"], *entry["data"], *entry["action"], *entry["response"]]
    ]
    edited = await client.patch(
        f"{path}/lines/{lines[1]['id']}",
        json={"action": "edit", "text": text},
        headers={"If-Match": '"v1"'},
    )
    assert edited.status_code == 200
    version = edited.json()["version"]
    for line in lines:
        if line["status"] != "source_found" and line["id"] != lines[1]["id"]:
            confirmed = await client.patch(
                f"{path}/lines/{line['id']}",
                json={"action": "confirm"},
                headers={"If-Match": f'"v{version}"'},
            )
            assert confirmed.status_code == 200
            version = confirmed.json()["version"]
    signed = await client.post(
        f"{path}/sign", json={"pin": DEMO_PIN}, headers={"If-Match": f'"v{version}"'}
    )
    assert signed.status_code == 200, signed.text


@pytest.mark.asyncio
async def test_logs_never_contain_note_text_or_names(
    app: FastAPI,
    client: httpx.AsyncClient,
    caplog: pytest.LogCaptureFixture,
    capfd: pytest.CaptureFixture[str],
) -> None:
    for name in list(logging.root.manager.loggerDict):
        pinned = any(name == pin or name.startswith(pin + ".") for pin in QUIET_LOGGERS)
        if not pinned and isinstance(logging.root.manager.loggerDict[name], logging.Logger):
            caplog.set_level(logging.DEBUG, logger=name)
    caplog.set_level(logging.DEBUG)
    for pin in QUIET_LOGGERS:
        assert logging.getLogger(pin).getEffectiveLevel() >= logging.WARNING
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
        # Post the case's own note and run its job: the text goes through the real pipeline.
        await sign_in(client, STAFF_NURSE[case.facility_key])
        posted = await post_note(client, case.patient_id, case.rough_note.text, key=case.key)
        assert posted.status_code == 202
        await drain(app)
        job = await client.get(f"/api/v1/draft-jobs/{posted.json()['id']}")
        assert job.json()["status"] == "succeeded"
        await client.get(f"/api/v1/patients/{case.patient_id}")
        await review_and_sign(client, job.json()["note_id"], edit_text(case))
        assert (await client.delete("/api/v1/session")).status_code == 204
    captured = capfd.readouterr()
    everything = (caplog.text + captured.out + captured.err).lower()
    assert "request" in [line.get("event") for line in json_lines(captured.out)]
    assert caplog.records
    assert leaked(everything, cases) == []
    # The check can fail: a planted leak through a project logger is caught.
    planted = forbidden_words(cases[0])
    logging.getLogger("nursing_core.planted").warning(max(planted, key=len))
    assert leaked(caplog.text + capfd.readouterr().out, cases)
    # Nor would a logged edit text go unnoticed: it is a stretch of the rough note.
    caplog.clear()
    logging.getLogger("nursing_core.planted").warning(edit_text(cases[0]))
    assert leaked(caplog.text, cases)


CANARY = "zebracanary patient Qorvex Dramblin"


@pytest.mark.asyncio
async def test_keys_off_the_allowlist_are_dropped_on_both_paths(
    app: FastAPI, capfd: pytest.CaptureFixture[str]
) -> None:
    del app
    structlog.get_logger("t").info("structlog event", patient_name=CANARY)
    logging.getLogger("nursing_core.t").warning("stdlib event", extra={"patient_name": CANARY})
    out = capfd.readouterr().out
    assert CANARY not in out
    assert "patient_name" not in out
    events = [line["event"] for line in json_lines(out)]
    assert events == ["structlog event", "stdlib event"]


@pytest.mark.asyncio
async def test_a_stdlib_message_never_has_its_arguments_filled_in(
    app: FastAPI, capfd: pytest.CaptureFixture[str]
) -> None:
    del app
    logging.getLogger("nursing_core.t").warning("filled %s", CANARY)
    logging.getLogger("some.library").warning("filled %s", CANARY)
    out = capfd.readouterr().out
    assert CANARY not in out
    assert [line["event"] for line in json_lines(out)] == ["filled %s", LIBRARY_EVENT]


@pytest.mark.asyncio
async def test_an_unretrieved_task_exception_is_logged_without_its_text(
    app: FastAPI, capfd: pytest.CaptureFixture[str]
) -> None:
    del app

    async def fail() -> None:
        raise ValueError(CANARY)

    task = asyncio.ensure_future(fail())
    await asyncio.sleep(0)
    del task

    gc.collect()
    out = capfd.readouterr()
    assert CANARY not in out.out + out.err
    lines = json_lines(out.out)
    assert lines
    assert {line["event"] for line in lines} == {LIBRARY_EVENT}


@pytest.mark.asyncio
async def test_uvicorn_error_logs_come_through_the_allowlist(
    database_url: str, capfd: pytest.CaptureFixture[str]
) -> None:
    import uvicorn.config
    from nursing_api.settings import Settings

    names = ("uvicorn", "uvicorn.error", "uvicorn.access")
    saved = {
        name: (logging.getLogger(name).handlers[:], logging.getLogger(name).propagate)
        for name in names
    }
    try:
        logging.config.dictConfig(uvicorn.config.LOGGING_CONFIG)  # what uvicorn does first
        create_app(Settings(database_url=database_url))  # then it calls the factory
        capfd.readouterr()
        try:
            raise RuntimeError(CANARY)
        except RuntimeError:
            logging.getLogger("uvicorn.error").error(
                "Exception in ASGI application\n", exc_info=True
            )
        captured = capfd.readouterr()
    finally:
        for name, (handlers, propagate) in saved.items():
            logging.getLogger(name).handlers[:] = handlers
            logging.getLogger(name).propagate = propagate
        configure_logging()
    assert CANARY not in captured.out + captured.err
    assert "Traceback" not in captured.out + captured.err
    [line] = json_lines(captured.out)
    assert line["event"] == LIBRARY_EVENT
    assert line["error_class"] == "RuntimeError"


@pytest.mark.asyncio
async def test_a_message_that_is_not_text_never_becomes_the_event(
    app: FastAPI, capfd: pytest.CaptureFixture[str]
) -> None:
    del app
    logging.getLogger("nursing_core.t").warning(ValueError(CANARY))  # pyright: ignore[reportArgumentType]
    out = capfd.readouterr().out
    assert CANARY not in out
    assert [line["event"] for line in json_lines(out)] == [LIBRARY_EVENT]


@pytest.mark.asyncio
async def test_a_uvicorn_template_is_the_event_and_its_arguments_are_not(
    app: FastAPI, capfd: pytest.CaptureFixture[str]
) -> None:
    del app
    logging.getLogger("uvicorn.error").info(
        "Uvicorn running on %s://%s:%d (Press CTRL+C to quit)", "http", CANARY, 8000
    )
    out = capfd.readouterr().out
    assert CANARY not in out
    assert [line["event"] for line in json_lines(out)] == [
        "Uvicorn running on %s://%s:%d (Press CTRL+C to quit)"
    ]


@pytest.mark.asyncio
async def test_an_api_response_is_not_stored_by_the_browser(
    client: httpx.AsyncClient,
) -> None:
    await sign_in(client, PH_STAFF)
    for path in ("/api/v1/session", "/api/v1/patients", "/api/v1/personas"):
        response = await client.get(path)
        assert response.headers["cache-control"] == "no-store", path
    unauthorised = await client.get("/api/v1/notes/" + str(uuid4()))
    assert unauthorised.headers["cache-control"] == "no-store"  # a problem answer too
    assert "cache-control" not in (await client.get("/api/v1/health")).headers


@pytest.mark.asyncio
async def test_an_unlisted_uvicorn_message_becomes_the_constant(
    app: FastAPI, capfd: pytest.CaptureFixture[str]
) -> None:
    del app
    logging.getLogger("uvicorn.error").error(f"Error loading ASGI app. {CANARY}")
    logging.getLogger("uvicorn.error").info("Started server process [%d]\nextra %s", 1, CANARY)
    out = capfd.readouterr().out
    assert CANARY not in out
    assert [line["event"] for line in json_lines(out)] == [LIBRARY_EVENT, LIBRARY_EVENT]


@pytest.mark.asyncio
async def test_an_unhashable_uvicorn_message_is_a_library_log_and_never_raises(
    app: FastAPI, capfd: pytest.CaptureFixture[str]
) -> None:
    del app
    logging.getLogger("uvicorn.error").info(["Quixley", {"nested": CANARY}])  # pyright: ignore[reportArgumentType]
    captured = capfd.readouterr()
    assert CANARY not in captured.out + captured.err
    assert "Traceback" not in captured.err
    [line] = json_lines(captured.out)
    assert line["event"] == LIBRARY_EVENT
    assert "error_class" not in line


@pytest.mark.parametrize("empty", [False, None, (None, None, None)])
@pytest.mark.asyncio
async def test_a_record_with_an_empty_exc_info_formats_as_having_none(
    app: FastAPI, capfd: pytest.CaptureFixture[str], empty: Any
) -> None:
    del app
    logging.getLogger("nursing_core.t").error("it failed", exc_info=empty)
    captured = capfd.readouterr()
    assert "Traceback" not in captured.err
    [line] = json_lines(captured.out)
    assert line["event"] == "it failed"
    assert "error_class" not in line


@pytest.mark.asyncio
async def test_a_formatter_error_never_prints_the_records_arguments(
    app: FastAPI, capfd: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    del app
    monkeypatch.setattr(logging, "raiseExceptions", True)
    configure_logging()
    assert logging.raiseExceptions is False

    handler = next(h for h in logging.getLogger().handlers if h.get_name() == "nursing_api.json")

    def broken_format(_record: logging.LogRecord) -> str:
        raise KeyError("x")

    monkeypatch.setattr(handler, "format", broken_format)
    logging.getLogger("nursing_core.t").error("value %s", "Zorblat-canary-word")
    captured = capfd.readouterr()
    assert "Zorblat-canary-word" not in captured.out + captured.err
    assert "Traceback" not in captured.err
