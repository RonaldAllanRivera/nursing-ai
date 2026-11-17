"""Saving a rough note: the session's shift, the facility's format, idempotency and visibility."""

from datetime import UTC, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from nursing_core.demo import load_demo_cases
from nursing_core.domain.shifts import ShiftRef

from .helpers import (
    ADMIN,
    PH_STAFF,
    US_STAFF,
    MutableClock,
    client_for,
    keep_open,
    post_note,
    running_app,
    sign_in,
)
from .test_budget import add_invited_nurse

PH_CASES = [case for case in load_demo_cases() if case.facility_key == "ph-demo"]
US_CASES = [case for case in load_demo_cases() if case.facility_key == "us-demo"]
PH_CASE = PH_CASES[0]
US_CASE = US_CASES[0]


@pytest.mark.asyncio
async def test_post_answers_202_with_a_location_and_a_queued_job(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    await sign_in(client, PH_STAFF)
    response = await post_note(client, PH_CASE.patient_id, "pt resting, no complaints")
    assert response.status_code == 202, response.text
    body = response.json()
    assert response.headers["location"] == f"/api/v1/draft-jobs/{body['id']}"
    assert body["status"] in {"queued", "running"}
    assert body["failure"] is None
    assert body["note_id"] is None
    await app.state.queue.drain()


@pytest.mark.asyncio
async def test_note_takes_the_sessions_shift_not_the_clocks(
    app: FastAPI, client: httpx.AsyncClient, clock: MutableClock
) -> None:
    # 13:00 in Manila (05:00 UTC): the nurse signs in to the 6-2 shift, then charts late at 14:10.
    clock.set(PH_CASE.rough_note.written_at.astimezone(UTC).replace(hour=5, minute=0))
    signed_in = await sign_in(client, PH_STAFF)
    session_shift = ShiftRef.model_validate(signed_in.json()["shift"])
    assert session_shift.code == "6-2"
    clock.advance(timedelta(hours=1, minutes=10))
    await keep_open(client)  # she charts late, but she has been at the keyboard all along
    response = await post_note(client, PH_CASE.patient_id, "late entry, pt comfortable")
    assert response.status_code == 202
    rough = await app.state.notes.get_rough_note(UUID(response.json()["rough_note_id"]))
    assert rough.shift == session_shift
    assert rough.written_at == clock.now()
    assert rough.author_id == PH_STAFF
    await app.state.queue.drain()


@pytest.mark.asyncio
async def test_note_takes_the_facilitys_default_format(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    await sign_in(client, US_STAFF)
    response = await post_note(client, US_CASE.patient_id, "pt resting")
    rough = await app.state.notes.get_rough_note(UUID(response.json()["rough_note_id"]))
    facility = await app.state.facilities.get_facility("us-demo")
    assert rough.note_format == facility.profile.default_note_format
    assert rough.encounter_id == US_CASE.rough_note.encounter_id
    await app.state.queue.drain()


@pytest.mark.asyncio
async def test_same_idempotency_key_returns_first_job(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    await sign_in(client, PH_STAFF)
    first = await post_note(client, PH_CASE.patient_id, "pt resting", key="tap-1")
    second = await post_note(client, PH_CASE.patient_id, "pt resting", key="tap-1")
    assert first.status_code == second.status_code == 202
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["rough_note_id"] == first.json()["rough_note_id"]
    assert second.headers["location"] == first.headers["location"]
    await app.state.queue.drain()
    again = await post_note(client, PH_CASE.patient_id, "pt resting", key="tap-1")
    assert again.json()["id"] == first.json()["id"]
    assert again.json()["status"] in {"succeeded", "failed"}  # the first job's current state
    detail = await client.get(f"/api/v1/patients/{PH_CASE.patient_id}")
    assert len(detail.json()["notes"]) == 1


@pytest.mark.asyncio
async def test_reused_key_with_other_text_is_422(app: FastAPI, client: httpx.AsyncClient) -> None:
    await sign_in(client, PH_STAFF)
    await post_note(client, PH_CASE.patient_id, "pt resting", key="tap-1")
    other = await post_note(client, PH_CASE.patient_id, "pt in pain", key="tap-1")
    assert other.status_code == 422
    assert other.json()["code"] == "idempotency_key_reused"
    await app.state.queue.drain()


@pytest.mark.asyncio
async def test_reused_key_for_another_patient_is_422(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    await sign_in(client, PH_STAFF)
    await post_note(client, PH_CASES[0].patient_id, "pt resting", key="tap-1")
    reused = await post_note(client, PH_CASES[1].patient_id, "pt resting", key="tap-1")
    assert reused.status_code == 422
    assert reused.json()["code"] == "idempotency_key_reused"
    await app.state.queue.drain()


@pytest.mark.asyncio
async def test_missing_idempotency_key_is_428(client: httpx.AsyncClient) -> None:
    await sign_in(client, PH_STAFF)
    response = await client.post(
        f"/api/v1/patients/{PH_CASE.patient_id}/rough-notes", json={"text": "pt resting"}
    )
    assert response.status_code == 428
    assert response.json()["code"] == "precondition_required"


@pytest.mark.asyncio
async def test_check_order_is_401_then_403_then_428_then_404(client: httpx.AsyncClient) -> None:
    path = f"/api/v1/patients/{uuid4()}/rough-notes"
    body = {"text": "pt resting"}
    assert (await client.post(path, json=body)).status_code == 401
    await sign_in(client, ADMIN)
    assert (await client.post(path, json=body)).status_code == 403
    await sign_in(client, PH_STAFF)
    assert (await client.post(path, json=body)).status_code == 428
    assert (await post_note(client, uuid4(), "pt resting")).status_code == 404


@pytest.mark.asyncio
async def test_admin_is_403_even_with_an_invalid_body(client: httpx.AsyncClient) -> None:
    await sign_in(client, ADMIN)
    response = await client.post(
        f"/api/v1/patients/{PH_CASE.patient_id}/rough-notes",
        json={"text": "x" * 5000},
        headers={"Idempotency-Key": "k"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_is_403_on_the_shift_route_even_with_an_invalid_body(
    client: httpx.AsyncClient,
) -> None:
    await sign_in(client, ADMIN)
    assert (await client.put("/api/v1/session/shift", json={"nope": 1})).status_code == 403


@pytest.mark.asyncio
async def test_a_nurse_cannot_post_for_another_facilitys_patient(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    await sign_in(client, PH_STAFF)
    response = await post_note(client, US_CASE.patient_id, "pt resting")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"
    await app.state.queue.drain()


@pytest.mark.asyncio
async def test_job_route_is_visible_to_the_facility_only(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    await sign_in(client, PH_STAFF)
    job = (await post_note(client, PH_CASE.patient_id, "pt resting")).json()
    await app.state.queue.drain()
    own = await client.get(f"/api/v1/draft-jobs/{job['id']}")
    assert own.status_code == 200
    assert own.json()["id"] == job["id"]
    assert (await client.get(f"/api/v1/draft-jobs/{uuid4()}")).status_code == 404
    await sign_in(client, US_STAFF)
    assert (await client.get(f"/api/v1/draft-jobs/{job['id']}")).status_code == 404
    await sign_in(client, ADMIN)
    assert (await client.get(f"/api/v1/draft-jobs/{job['id']}")).status_code == 403
    client.cookies.clear()
    assert (await client.get(f"/api/v1/draft-jobs/{job['id']}")).status_code == 401


@pytest.mark.asyncio
async def test_invalid_request_is_a_problem_that_never_echoes_input(
    client: httpx.AsyncClient,
) -> None:
    await sign_in(client, PH_STAFF)
    canary = "zebracanary-note-text"
    response = await post_note(client, PH_CASE.patient_id, canary * 400)
    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "invalid_request"
    assert canary not in response.text


@pytest.mark.asyncio
async def test_invalid_request_lists_the_fields_without_the_input(
    client: httpx.AsyncClient,
) -> None:
    await sign_in(client, PH_STAFF)
    response = await post_note(client, PH_CASE.patient_id, "x" * 4001)
    assert response.status_code == 422
    assert response.json()["errors"] == [
        {"field": "body.text", "message": "String should have at most 4000 characters"}
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["pt still\u0000 weak", "   \n  "])
async def test_a_nul_character_or_a_blank_note_is_invalid(
    client: httpx.AsyncClient, text: str
) -> None:
    await sign_in(client, PH_STAFF)
    assert (await post_note(client, PH_CASE.patient_id, text)).status_code == 422


@pytest.mark.asyncio
async def test_an_idempotency_key_over_200_characters_is_422_without_echoing_it(
    client: httpx.AsyncClient,
) -> None:
    await sign_in(client, PH_STAFF)
    path = f"/api/v1/patients/{PH_CASE.patient_id}/rough-notes"
    too_long = "k" * 201
    response = await client.post(
        path, json={"text": "pt resting"}, headers={"Idempotency-Key": too_long}
    )
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "invalid_request"
    assert body["errors"] == [{"field": "header.Idempotency-Key", "message": "too long"}]
    assert too_long not in response.text
    fine = await client.post(
        path, json={"text": "pt resting"}, headers={"Idempotency-Key": "k" * 200}
    )
    assert fine.status_code == 202


@pytest.mark.asyncio
async def test_draft_past_the_daily_cap_is_429(database_url: str, clock: MutableClock) -> None:
    async with running_app(database_url, clock, ai_daily_drafts_per_user=2) as app:
        async with client_for(app) as client:
            invited = await add_invited_nurse(app, "ph-demo")
            await sign_in(client, invited)
            first = await post_note(client, PH_CASE.patient_id, "pt resting", key="d-1")
            second = await post_note(client, PH_CASE.patient_id, "pt resting well", key="d-2")
            third = await post_note(client, PH_CASE.patient_id, "pt resting again", key="d-3")
            assert (first.status_code, second.status_code) == (202, 202)
            assert third.status_code == 429
            assert third.json()["code"] == "daily_draft_limit"
            # A replay of the first request at the cap returns its job.
            again = await post_note(client, PH_CASE.patient_id, "pt resting", key="d-1")
            assert again.status_code == 202
            assert again.json()["id"] == first.json()["id"]
            # A day later the count has rolled off.
            clock.advance(timedelta(hours=24, minutes=1))
            await sign_in(client, invited)  # her session ended meanwhile
            later = await post_note(client, PH_CASE.patient_id, "pt resting later", key="d-4")
            assert later.status_code == 202
        # A persona with the same setting is never capped.
        async with client_for(app) as persona_client:
            await sign_in(persona_client, PH_STAFF)
            for number in range(4):
                posted = await post_note(
                    persona_client, PH_CASE.patient_id, f"persona note {number}", key=f"p-{number}"
                )
                assert posted.status_code == 202
        await app.state.queue.drain()


@pytest.mark.asyncio
async def test_no_daily_cap_setting_means_no_cap(database_url: str, clock: MutableClock) -> None:
    async with running_app(database_url, clock) as app, client_for(app) as client:
        await sign_in(client, await add_invited_nurse(app, "ph-demo"))
        for number in range(3):
            posted = await post_note(
                client, PH_CASE.patient_id, f"note {number}", key=f"n-{number}"
            )
            assert posted.status_code == 202
        await app.state.queue.drain()
