"""The patient routes: a facility's list, and one patient with the session's shift."""

from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from nursing_core.demo import load_demo_cases
from nursing_core.domain.shifts import shift_choices

from .helpers import ADMIN, PH_STAFF, STAFF_NURSE, US_STAFF, MutableClock, post_note, sign_in

CASES = load_demo_cases()
PH_CASE = next(c for c in CASES if c.facility_key == "ph-demo")


@pytest.mark.asyncio
@pytest.mark.parametrize("facility_key", ["ph-demo", "us-demo"])
async def test_a_nurse_lists_only_her_facilitys_patients_in_the_repositorys_order(
    app: FastAPI, client: httpx.AsyncClient, facility_key: str
) -> None:
    await sign_in(client, STAFF_NURSE[facility_key])
    response = await client.get("/api/v1/patients")
    assert response.status_code == 200
    expected = await app.state.patients.list_patients(facility_key)
    assert expected
    assert response.json() == [p.model_dump(mode="json") for p in expected]
    assert {p["facility_key"] for p in response.json()} == {facility_key}


@pytest.mark.asyncio
async def test_list_needs_a_nurse(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/patients")).status_code == 401
    await sign_in(client, ADMIN)
    assert (await client.get("/api/v1/patients")).status_code == 403


@pytest.mark.asyncio
async def test_detail_has_the_summary_the_session_shift_and_its_notes(
    app: FastAPI, client: httpx.AsyncClient, clock: MutableClock
) -> None:
    signed_in = await sign_in(client, PH_STAFF)
    empty = await client.get(f"/api/v1/patients/{PH_CASE.patient_id}")
    assert empty.status_code == 200
    assert empty.json()["summary"]["id"] == str(PH_CASE.patient_id)
    assert empty.json()["summary"]["display_name"] == PH_CASE.display_name
    assert empty.json()["shift"] == signed_in.json()["shift"]
    assert empty.json()["notes"] == []
    first = (await post_note(client, PH_CASE.patient_id, "first note", key="a")).json()
    clock.advance(timedelta(minutes=1))
    second = (await post_note(client, PH_CASE.patient_id, "second note", key="b")).json()
    await app.state.queue.drain()
    notes = (await client.get(f"/api/v1/patients/{PH_CASE.patient_id}")).json()["notes"]
    assert [n["rough_note_id"] for n in notes] == [first["rough_note_id"], second["rough_note_id"]]
    assert [n["job"]["id"] for n in notes] == [first["id"], second["id"]]
    assert all(n["job"]["status"] in {"succeeded", "failed"} for n in notes)


@pytest.mark.asyncio
async def test_detail_shows_only_the_sessions_shift(
    app: FastAPI, client: httpx.AsyncClient, clock: MutableClock
) -> None:
    await sign_in(client, PH_STAFF)
    await post_note(client, PH_CASE.patient_id, "this shift")
    await app.state.queue.drain()
    shift = (await client.get("/api/v1/session")).json()["shift"]
    profile = (await app.state.facilities.get_facility("ph-demo")).profile
    other = next(s for s in shift_choices(clock.now(), profile) if s.code != shift["code"])
    switched = await client.put(
        "/api/v1/session/shift", json={"starts_at": other.starts_at.isoformat()}
    )
    assert switched.status_code == 200
    detail = (await client.get(f"/api/v1/patients/{PH_CASE.patient_id}")).json()
    assert detail["shift"]["code"] == other.code
    assert detail["notes"] == []


@pytest.mark.asyncio
async def test_detail_visibility(client: httpx.AsyncClient) -> None:
    path = f"/api/v1/patients/{PH_CASE.patient_id}"
    assert (await client.get(path)).status_code == 401
    await sign_in(client, US_STAFF)
    assert (await client.get(path)).status_code == 404
    assert (await client.get(f"/api/v1/patients/{uuid4()}")).status_code == 404
    await sign_in(client, ADMIN)
    assert (await client.get(path)).status_code == 403
