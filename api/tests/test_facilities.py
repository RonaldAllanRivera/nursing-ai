"""The admin's facility settings: who may read and edit them, the ETag, and the kept history."""

from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from nursing_api.schemas import FacilityUpdateIn
from nursing_core.demo import DEMO_PIN, load_demo_cases
from nursing_core.storage import tables
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError

from .helpers import ADMIN, PH_HEAD, PH_STAFF, US_STAFF, client_for, drain, post_note, sign_in

PH_CASE = load_demo_cases()[0]
PH = "/api/v1/facilities/ph-demo"
US = "/api/v1/facilities/us-demo"
SEVEN_TO_SEVEN = [
    ("7-3", "07:00:00", "15:00:00"),
    ("3-11", "15:00:00", "23:00:00"),
    ("11-7", "23:00:00", "07:00:00"),
]


def match(version: int) -> dict[str, str]:
    return {"If-Match": f'"f{version}"'}


async def settings_of(client: httpx.AsyncClient, path: str = PH) -> dict[str, Any]:
    """The facility's current settings as a PUT body: its profile without the key."""
    profile: dict[str, Any] = (await client.get(path)).json()["profile"]
    profile.pop("key")
    return profile | {"pin": DEMO_PIN}


def without_pin(body: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in body.items() if k != "pin"}


def moved_shifts(body: dict[str, Any]) -> dict[str, Any]:
    shifts = [
        dict(old, code=code, label=code, starts_local=start, ends_local=end)
        for old, (code, start, end) in zip(body["shifts"], SEVEN_TO_SEVEN, strict=True)
    ]
    return body | {"shifts": shifts, "day_starts_at": "07:00:00"}


async def history(app: FastAPI, key: str) -> list[Any]:
    async with app.state.engine.begin() as conn:
        rows = await conn.execute(
            select(tables.facility_change)
            .join(tables.facility, tables.facility.c.id == tables.facility_change.c.facility_id)
            .where(tables.facility.c.key == key)
            .order_by(tables.facility_change.c.version)
        )
        return list(rows)


@pytest.mark.asyncio
async def test_admin_edits_both_facilities(app: FastAPI, client: httpx.AsyncClient) -> None:
    await sign_in(client, ADMIN)
    listed = await client.get("/api/v1/facilities")
    assert [f["profile"]["key"] for f in listed.json()] == ["ph-demo", "us-demo"]
    for path, version in ((PH, 1), (US, 1)):
        read = await client.get(path)
        assert read.status_code == 200
        assert read.headers["etag"] == f'"f{version}"'
        assert len(read.json()["shift_choices"]) == 3
        body = await settings_of(client, path)
        body["name"] = "Renamed SYNTHETIC"
        saved = await client.put(path, json=body, headers=match(version))
        assert saved.status_code == 200, saved.text
        assert saved.headers["etag"] == f'"f{version + 1}"'
        assert saved.json()["version"] == version + 1
        assert saved.json()["profile"]["name"] == "Renamed SYNTHETIC"
        assert (await client.get(path)).json()["profile"]["name"] == "Renamed SYNTHETIC"


@pytest.mark.asyncio
async def test_nurse_reads_only_her_own_facility_403(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    await sign_in(client, PH_STAFF)
    listed = await client.get("/api/v1/facilities")
    assert [f["profile"]["key"] for f in listed.json()] == ["ph-demo"]
    assert (await client.get(PH)).status_code == 200
    for path in (US, "/api/v1/facilities/nowhere"):
        other = await client.get(path)
        assert other.status_code == 403, path
        assert other.json()["code"] == "forbidden"
    await client.delete("/api/v1/session")
    assert (await client.get("/api/v1/facilities")).status_code == 401
    await sign_in(client, ADMIN)
    assert (await client.get("/api/v1/facilities/nowhere")).status_code == 404


@pytest.mark.asyncio
async def test_admin_updates_the_shifts_and_new_sessions_use_them(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    await sign_in(client, ADMIN)
    body = moved_shifts(await settings_of(client))
    saved = await client.put(PH, json=body, headers=match(1))
    assert saved.status_code == 200, saved.text
    assert [s["code"] for s in saved.json()["profile"]["shifts"]] == ["7-3", "3-11", "11-7"]
    assert {s["code"] for s in saved.json()["shift_choices"]} == {"7-3", "3-11", "11-7"}
    nurse = await sign_in(client, PH_STAFF)
    assert nurse.json()["shift"]["code"] == "7-3"


@pytest.mark.asyncio
async def test_an_open_session_keeps_its_shift_after_an_admin_edit(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    async with client_for(app) as admin:
        await sign_in(client, PH_STAFF)
        await sign_in(admin, ADMIN)
        body = moved_shifts(await settings_of(admin))
        assert (await admin.put(PH, json=body, headers=match(1))).status_code == 200
    kept = await client.get("/api/v1/session")
    assert kept.json()["shift"]["code"] == "6-2"
    # Her choices now come from the new profile: the old shift can no longer be picked again.
    old = kept.json()["shift"]["starts_at"]
    assert (await client.put("/api/v1/session/shift", json={"starts_at": old})).status_code == 422
    choices = (await client.get(PH)).json()["shift_choices"]
    switched = await client.put(
        "/api/v1/session/shift", json={"starts_at": choices[1]["starts_at"]}
    )
    assert switched.status_code == 200
    assert switched.json()["shift"]["code"] == "7-3"


@pytest.mark.asyncio
async def test_old_notes_keep_their_shift_after_an_admin_edit(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    await sign_in(client, PH_STAFF)
    posted = await post_note(client, PH_CASE.patient_id, PH_CASE.rough_note.text)
    assert posted.status_code == 202, posted.text
    await drain(app)
    rough_id = posted.json()["rough_note_id"]
    before = await app.state.notes.get_rough_note(rough_id)
    assert before.shift.code == "6-2"
    await client.delete("/api/v1/session")
    await sign_in(client, ADMIN)
    body = moved_shifts(await settings_of(client))
    assert (await client.put(PH, json=body, headers=match(1))).status_code == 200
    after = await app.state.notes.get_rough_note(rough_id)
    assert after.shift == before.shift
    assert after.note_format == before.note_format


@pytest.mark.asyncio
async def test_nurse_cannot_edit_settings_403(app: FastAPI, client: httpx.AsyncClient) -> None:
    await sign_in(client, ADMIN)
    body = await settings_of(client)
    for persona in (PH_STAFF, PH_HEAD, US_STAFF):
        await client.delete("/api/v1/session")
        await sign_in(client, persona)
        for path in (PH, US):
            denied = await client.put(path, json=body, headers=match(1))
            assert denied.status_code == 403, (persona, path)
            assert denied.json()["code"] == "forbidden"
        # 403 comes before the body is looked at, and before the header is required.
        assert (await client.put(PH, json={"nope": 1})).status_code == 403
    assert (await app.state.facilities.get_facility("ph-demo")).version == 1
    await client.delete("/api/v1/session")
    assert (await client.put(PH, json=body, headers=match(1))).status_code == 401


@pytest.mark.asyncio
async def test_admin_cannot_write_or_sign_notes_403(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    await sign_in(client, PH_STAFF)
    posted = await post_note(client, PH_CASE.patient_id, PH_CASE.rough_note.text)
    await drain(app)
    job = await client.get(f"/api/v1/draft-jobs/{posted.json()['id']}")
    note_id = job.json()["note_id"]
    await client.delete("/api/v1/session")
    await sign_in(client, ADMIN)
    refused = [
        await post_note(client, PH_CASE.patient_id, "pt resting", key="admin-1"),
        await client.patch(
            f"/api/v1/notes/{note_id}/lines/e1-D2",
            json={"action": "confirm"},
            headers=match(1) | {"If-Match": '"v1"'},
        ),
        await client.post(
            f"/api/v1/notes/{note_id}/sign", json={"pin": DEMO_PIN}, headers={"If-Match": '"v1"'}
        ),
        await client.post(f"/api/v1/notes/{note_id}/discard", headers={"If-Match": '"v1"'}),
    ]
    assert [r.status_code for r in refused] == [403, 403, 403, 403]
    assert {r.json()["code"] for r in refused} == {"forbidden"}
    assert (await app.state.notes.get_note(note_id)).version == 1


@pytest.mark.asyncio
async def test_settings_edit_with_stale_etag_is_412(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    await sign_in(client, ADMIN)
    body = await settings_of(client)
    assert (await client.put(PH, json=body, headers=match(1))).status_code == 200
    for stale in ('"f1"', '"v2"', "f2", "*", '"f02"', 'W/"f2"'):
        response = await client.put(PH, json=body, headers={"If-Match": stale})
        assert response.status_code == 412, stale
        assert response.json()["code"] == "stale_version"
    assert (await app.state.facilities.get_facility("ph-demo")).version == 2
    assert (await client.put(PH, json=body, headers=match(2))).status_code == 200


@pytest.mark.asyncio
async def test_a_race_for_the_same_version_is_412_for_the_loser(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    await sign_in(client, ADMIN)
    body = await settings_of(client)
    # Someone saves between this admin's check and save: the repository's own version check.
    await app.state.facilities.update_facility(
        "ph-demo", FacilityUpdateIn.model_validate(body).settings(), 1, ADMIN
    )
    response = await client.put(PH, json=body, headers=match(1))
    assert response.status_code == 412


@pytest.mark.asyncio
async def test_settings_edit_without_if_match_is_428(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    await sign_in(client, ADMIN)
    body = await settings_of(client)
    response = await client.put(PH, json=body)
    assert response.status_code == 428
    assert response.json()["code"] == "precondition_required"
    # An unknown facility without the header is still 428 first; with it, 404.
    assert (await client.put("/api/v1/facilities/nowhere", json=body)).status_code == 428
    gone = await client.put("/api/v1/facilities/nowhere", json=body, headers=match(1))
    assert gone.status_code == 404
    assert (await app.state.facilities.get_facility("ph-demo")).version == 1


@pytest.mark.asyncio
async def test_settings_that_dont_tile_the_day_are_422(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    await sign_in(client, ADMIN)
    body = await settings_of(client)
    gap = body | {"shifts": [dict(s) for s in body["shifts"]]}
    gap["shifts"][1]["ends_local"] = "21:00:00"
    response = await client.put(PH, json=gap, headers=match(1))
    assert response.status_code == 422
    assert response.json()["errors"] == [
        {"field": "body", "message": "shifts must cover 24 hours with no gap or overlap"}
    ]
    late = body | {"day_starts_at": "05:00:00"}
    assert (await client.put(PH, json=late, headers=match(1))).status_code == 422
    assert (await app.state.facilities.get_facility("ph-demo")).version == 1


@pytest.mark.asyncio
async def test_key_cannot_be_changed(app: FastAPI, client: httpx.AsyncClient) -> None:
    await sign_in(client, ADMIN)
    body = await settings_of(client) | {"key": "stolen-qorvex-key"}
    response = await client.put(PH, json=body, headers=match(1))
    assert response.status_code == 422
    assert response.json()["errors"] == [{"field": "body", "message": "unknown field"}]
    assert "stolen" not in response.text
    assert (await app.state.facilities.get_facility("ph-demo")).version == 1
    assert [f["profile"]["key"] for f in (await client.get("/api/v1/facilities")).json()] == [
        "ph-demo",
        "us-demo",
    ]


@pytest.mark.asyncio
async def test_every_save_is_kept_in_facility_change(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    await sign_in(client, ADMIN)
    first = await settings_of(client)
    second = moved_shifts(first)
    assert (await client.put(PH, json=second, headers=match(1))).status_code == 200
    third = second | {"name": "Third SYNTHETIC"}
    assert (await client.put(PH, json=third, headers=match(2))).status_code == 200
    rows = await history(app, "ph-demo")
    assert [row.version for row in rows] == [1, 2, 3]
    assert rows[0].changed_by is None
    assert [row.changed_by for row in rows[1:]] == [ADMIN, ADMIN]
    assert rows[1].settings == without_pin(second)
    assert rows[2].settings == without_pin(third)
    assert rows[0].settings == without_pin(first)
    # The PIN proves who saved; it is never part of the facility's history.
    assert all("pin" not in row.settings for row in rows)
    assert len(await history(app, "us-demo")) == 1
    # The database refuses to rewrite the kept history, even for the app's own connection.
    async with app.state.engine.begin() as conn:
        with pytest.raises(DBAPIError, match="not allowed"):
            await conn.execute(update(tables.facility_change).values(changed_by=None))


@pytest.mark.asyncio
async def test_a_rule_about_the_whole_form_is_named_body(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    await sign_in(client, ADMIN)
    body = await settings_of(client)
    body["shifts"][1]["ends_local"] = "21:00:00"
    response = await client.put(PH, json=body, headers=match(1))
    assert response.status_code == 422
    assert response.json()["errors"] == [
        {"field": "body", "message": "shifts must cover 24 hours with no gap or overlap"}
    ]


@pytest.mark.asyncio
async def test_oversized_timezone_is_invalid_not_a_crash(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    await sign_in(client, ADMIN)
    body = await settings_of(client) | {"timezone": "A" * 300}
    response = await client.put(PH, json=body, headers=match(1))
    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "body.timezone"


@pytest.mark.asyncio
async def test_settings_save_needs_the_pin(app: FastAPI, client: httpx.AsyncClient) -> None:
    await sign_in(client, ADMIN)
    body = await settings_of(client)
    body["name"] = "Renamed SYNTHETIC"

    wrong = await client.put(PH, json=body | {"pin": "864209"}, headers=match(1))
    stale = await client.put(PH, json=body | {"pin": "864209"}, headers=match(7))
    missing = await client.put(PH, json=without_pin(body), headers=match(1))

    assert (wrong.status_code, wrong.json()["code"], wrong.json()["tries_left"]) == (
        403,
        "pin_wrong",
        4,
    )
    assert (stale.status_code, missing.status_code) == (412, 422)  # If-Match first; the schema
    assert (await client.get(PH)).json()["version"] == 1  # nothing was saved
    saved = await client.put(PH, json=body, headers=match(1))
    assert saved.status_code == 200, saved.text
    assert saved.json()["version"] == 2
    assert len(await history(app, "ph-demo")) == 2
    # Five wrong PINs on saves end the admin persona's session.
    answers = [
        await client.put(PH, json=body | {"pin": "864209"}, headers=match(2)) for _ in range(5)
    ]
    assert [a.status_code for a in answers] == [403, 403, 403, 403, 401]
    assert (await client.get(PH)).status_code == 401
