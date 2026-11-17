"""Reading a draft note, reviewing its lines, signing it into the record, or discarding it."""

from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from nursing_core.demo import DEMO_PIN, DemoCase, load_demo_cases
from nursing_core.domain.facility import FacilitySettings
from nursing_core.domain.hashing import SignedContent, content_hash, signed_content
from nursing_core.domain.notes import NoteStatus, unresolved_line_ids
from nursing_core.domain.units import Ucum
from nursing_core.storage import tables
from sqlalchemy import func, select

from .helpers import (
    ADMIN,
    PH_HEAD,
    PH_STAFF,
    US_STAFF,
    MutableClock,
    client_for,
    drain,
    post_note,
    sign_in,
)

SIGN = {"pin": DEMO_PIN}

CASES = load_demo_cases()
PH_CASE = CASES[0]
FLAGGED = ["e1-F", "e1-D2", "e1-A2"]  # demo-1's lines that need the nurse
V1 = {"If-Match": '"v1"'}


async def make_draft(
    app: FastAPI, client: httpx.AsyncClient, case: DemoCase = PH_CASE, key: str = "key-1"
) -> UUID:
    """Post the case's own note as the signed-in nurse, run its job, return the draft's id."""
    posted = await post_note(client, case.patient_id, case.rough_note.text, key=key)
    assert posted.status_code == 202, posted.text
    await drain(app)
    job = await client.get(f"/api/v1/draft-jobs/{posted.json()['id']}")
    assert job.json()["status"] == "succeeded", job.text
    return UUID(job.json()["note_id"])


def url(note_id: UUID, tail: str = "") -> str:
    return f"/api/v1/notes/{note_id}{tail}"


def line_url(note_id: UUID, line_id: str) -> str:
    return url(note_id, f"/lines/{line_id}")


async def confirm_flagged_from(
    client: httpx.AsyncClient, note_id: UUID, line_ids: list[str], version: int
) -> httpx.Response:
    """Confirm the given lines one after another, starting at the note's current version."""
    response = await client.get(url(note_id))
    for line_id in line_ids:
        response = await client.patch(
            line_url(note_id, line_id), json={"action": "confirm"}, headers=ifm(version)
        )
        assert response.status_code == 200, response.text
        version = response.json()["version"]
    return response


async def confirm_flagged(client: httpx.AsyncClient, note_id: UUID) -> httpx.Response:
    current = (await client.get(url(note_id))).json()["version"]
    return await confirm_flagged_from(client, note_id, FLAGGED, current)


def ifm(version: int) -> dict[str, str]:
    return {"If-Match": f'"v{version}"'}


def line_of(body: dict[str, Any], line_id: str) -> dict[str, Any]:
    for entry in body["draft"]["entries"]:
        for line in [entry["focus"], *entry["data"], *entry["action"], *entry["response"]]:
            if line["id"] == line_id:
                found: dict[str, Any] = line
                return found
    raise AssertionError(line_id)


async def note_versions(app: FastAPI, note_id: UUID) -> list[Any]:
    async with app.state.engine.begin() as conn:
        result = await conn.execute(
            select(tables.note_version).where(tables.note_version.c.note_id == note_id)
        )
        return list(result.all())


@pytest.mark.asyncio
async def test_get_note_has_etag(app: FastAPI, client: httpx.AsyncClient) -> None:
    await sign_in(client, PH_STAFF)
    note_id = await make_draft(app, client)
    response = await client.get(url(note_id))
    assert response.status_code == 200
    assert response.headers["etag"] == '"v1"'
    body = response.json()
    assert body["id"] == str(note_id)
    assert body["status"] == "draft"
    assert body["version"] == 1
    assert body["rough_note"]["text"] == PH_CASE.rough_note.text
    assert body["rough_note"]["shift"]["code"] == "6-2"
    assert body["patient"]["id"] == str(PH_CASE.patient_id)
    assert body["patient"]["display_name"] == PH_CASE.display_name
    assert body["signature"] is None
    assert body["discard"] is None
    stored = await app.state.notes.get_note(note_id)
    assert sorted(unresolved_line_ids(stored.draft)) == sorted(FLAGGED)


@pytest.mark.asyncio
async def test_a_line_change_bumps_the_version_and_the_etag(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    await sign_in(client, PH_STAFF)
    note_id = await make_draft(app, client)
    response = await client.patch(
        line_url(note_id, "e1-D2"), json={"action": "confirm"}, headers=V1
    )
    assert response.status_code == 200
    assert response.headers["etag"] == '"v2"'
    assert response.json()["version"] == 2
    assert line_of(response.json(), "e1-D2")["review"] == "confirmed"
    assert (await client.get(url(note_id))).headers["etag"] == '"v2"'


@pytest.mark.asyncio
async def test_a_change_that_changes_nothing_keeps_the_version(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    await sign_in(client, PH_STAFF)
    note_id = await make_draft(app, client)
    first = await client.patch(line_url(note_id, "e1-D2"), json={"action": "confirm"}, headers=V1)
    again = await client.patch(
        line_url(note_id, "e1-D2"), json={"action": "confirm"}, headers=ifm(2)
    )
    assert again.status_code == 200
    assert again.headers["etag"] == first.headers["etag"] == '"v2"'
    assert again.json() == first.json()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "tail", "body"),
    [
        ("PATCH", "/lines/e1-D2", {"action": "confirm"}),
        ("POST", "/sign", SIGN),
        ("POST", "/discard", None),
    ],
)
async def test_missing_if_match_is_428(
    app: FastAPI, client: httpx.AsyncClient, method: str, tail: str, body: Any
) -> None:
    await sign_in(client, PH_STAFF)
    note_id = await make_draft(app, client)
    response = await client.request(method, url(note_id, tail), json=body)
    assert response.status_code == 428
    assert response.json()["code"] == "precondition_required"
    assert (await client.get(url(note_id))).json()["version"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("stale", ['"v0"', '"v2"', "v1", 'W/"v1"', '"v1" ', "1", '""', "*"])
async def test_line_edit_with_stale_etag_is_412(
    app: FastAPI, client: httpx.AsyncClient, stale: str
) -> None:
    await sign_in(client, PH_STAFF)
    note_id = await make_draft(app, client)
    response = await client.patch(
        line_url(note_id, "e1-D2"), json={"action": "confirm"}, headers={"If-Match": stale}
    )
    assert response.status_code == 412
    assert response.json()["code"] == "stale_version"
    assert (await client.get(url(note_id))).json()["version"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("tail", ["/sign", "/discard"])
async def test_sign_and_discard_with_stale_etag_are_412(
    app: FastAPI, client: httpx.AsyncClient, tail: str
) -> None:
    await sign_in(client, PH_STAFF)
    note_id = await make_draft(app, client)
    await confirm_flagged(client, note_id)
    response = await client.post(url(note_id, tail), json=SIGN, headers=V1)
    assert response.status_code == 412


@pytest.mark.asyncio
async def test_remove_focus_line_is_422(app: FastAPI, client: httpx.AsyncClient) -> None:
    await sign_in(client, PH_STAFF)
    note_id = await make_draft(app, client)
    response = await client.patch(line_url(note_id, "e1-F"), json={"action": "remove"}, headers=V1)
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "invalid_request"
    assert body["errors"][0]["field"] == "body.action"
    assert (await client.get(url(note_id))).json()["version"] == 1


@pytest.mark.asyncio
async def test_confirming_a_removed_line_is_422(app: FastAPI, client: httpx.AsyncClient) -> None:
    await sign_in(client, PH_STAFF)
    note_id = await make_draft(app, client)
    await client.patch(line_url(note_id, "e1-A2"), json={"action": "remove"}, headers=V1)
    response = await client.patch(
        line_url(note_id, "e1-A2"), json={"action": "confirm"}, headers=ifm(2)
    )
    assert response.status_code == 422
    assert "restore" in response.json()["errors"][0]["message"]


@pytest.mark.asyncio
async def test_an_unknown_line_is_404(app: FastAPI, client: httpx.AsyncClient) -> None:
    await sign_in(client, PH_STAFF)
    note_id = await make_draft(app, client)
    response = await client.patch(line_url(note_id, "e9-X"), json={"action": "confirm"}, headers=V1)
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


@pytest.mark.asyncio
async def test_edit_recomputes_the_line_and_counts_as_reviewed(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    await sign_in(client, PH_STAFF)
    note_id = await make_draft(app, client)
    response = await client.patch(
        line_url(note_id, "e1-D2"),
        json={"action": "edit", "text": "BP 90/60 mmHg."},
        headers=V1,
    )
    assert response.status_code == 200
    line = line_of(response.json(), "e1-D2")
    assert (line["text"], line["review"], line["status"]) == (
        "BP 90/60 mmHg.",
        "edited",
        "source_found",
    )
    assert line["ai_text"] == "BP 90/60 mmHg, HR 121 bpm."


@pytest.mark.asyncio
async def test_restore_brings_back_the_ai_text_as_pending(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    await sign_in(client, PH_STAFF)
    note_id = await make_draft(app, client)
    original = line_of((await client.get(url(note_id))).json(), "e1-D1")
    edited = await client.patch(
        line_url(note_id, "e1-D1"), json={"action": "edit", "text": "Dizzy."}, headers=V1
    )
    assert line_of(edited.json(), "e1-D1")["review"] == "edited"
    restored = await client.patch(
        line_url(note_id, "e1-D1"), json={"action": "restore"}, headers=ifm(2)
    )
    assert restored.status_code == 200
    line = line_of(restored.json(), "e1-D1")
    assert line["text"] == original["ai_text"]
    assert line["review"] == "pending"


@pytest.mark.asyncio
async def test_a_restored_source_found_line_needs_a_confirm_before_signing(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    await sign_in(client, PH_STAFF)
    note_id = await make_draft(app, client)
    drafted = line_of((await client.get(url(note_id))).json(), "e1-D1")
    assert drafted["status"] == "source_found"  # it needed no confirm as drafted
    restored = await client.patch(
        line_url(note_id, "e1-D1"), json={"action": "restore"}, headers=V1
    )
    assert restored.status_code == 200
    line = line_of(restored.json(), "e1-D1")
    # The cautious reading (PLAN 14.11): restore can't know whether the model called the line its
    # own wording, so it takes the stricter reading: a summary, which needs one more confirm.
    assert (line["status"], line["review"]) == ("summary", "pending")
    await confirm_flagged_from(client, note_id, FLAGGED, restored.json()["version"])
    refused = await client.post(url(note_id, "/sign"), json=SIGN, headers=ifm(5))
    assert refused.status_code == 409
    assert refused.json()["code"] == "review_incomplete"
    assert refused.json()["line_ids"] == ["e1-D1"]


@pytest.mark.asyncio
async def test_a_removed_line_can_be_restored(app: FastAPI, client: httpx.AsyncClient) -> None:
    await sign_in(client, PH_STAFF)
    note_id = await make_draft(app, client)
    removed = await client.patch(line_url(note_id, "e1-A2"), json={"action": "remove"}, headers=V1)
    assert line_of(removed.json(), "e1-A2")["review"] == "removed"
    restored = await client.patch(
        line_url(note_id, "e1-A2"), json={"action": "restore"}, headers=ifm(2)
    )
    assert line_of(restored.json(), "e1-A2")["review"] == "pending"


@pytest.mark.asyncio
async def test_an_edit_rechecks_with_the_facilitys_current_units(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    await sign_in(client, PH_STAFF)
    note_id = await make_draft(app, client)
    edit = {"action": "edit", "text": "Shivering at around 3 AM, temperature 37.9 °C."}
    before = await client.patch(line_url(note_id, "e1-D3"), json=edit, headers=V1)
    assert line_of(before.json(), "e1-D3")["status"] == "source_found"
    # The facility switches to Fahrenheit: the same edit now disagrees with a note without a unit.
    facility = await app.state.facilities.get_facility("ph-demo")
    changed = facility.profile.model_copy(
        update={"units": facility.profile.units.model_copy(update={"temperature": Ucum.DEG_F})}
    )
    await app.state.facilities.update_facility(
        "ph-demo",
        FacilitySettings.model_validate(changed.model_dump(exclude={"key"})),
        facility.version,
        ADMIN,
    )
    after = await client.patch(
        line_url(note_id, "e1-D3"), json=edit | {"text": edit["text"] + " "}, headers=ifm(2)
    )
    assert after.status_code == 200
    assert line_of(after.json(), "e1-D3")["status"] == "number_mismatch"


@pytest.mark.asyncio
async def test_sign_refused_while_lines_need_review(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    await sign_in(client, PH_STAFF)
    note_id = await make_draft(app, client)
    response = await client.post(url(note_id, "/sign"), json=SIGN, headers=V1)
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "review_incomplete"
    assert sorted(body["line_ids"]) == sorted(FLAGGED)
    assert (await client.get(url(note_id))).json()["status"] == "draft"
    assert await note_versions(app, note_id) == []


@pytest.mark.asyncio
async def test_sign_hashes_signed_content(
    app: FastAPI, client: httpx.AsyncClient, clock: MutableClock
) -> None:
    await sign_in(client, PH_STAFF)
    note_id = await make_draft(app, client)
    confirmed = await confirm_flagged(client, note_id)
    before = await app.state.notes.get_note(note_id)
    rough = await app.state.notes.get_rough_note(before.rough_note_id)
    expected = signed_content(before, rough, PH_STAFF, clock.now())
    response = await client.post(
        url(note_id, "/sign"), json=SIGN, headers=ifm(confirmed.json()["version"])
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "signed"
    assert response.headers["etag"] == f'"v{before.version + 1}"'
    assert body["signature"]["content_hash"] == content_hash(expected)
    assert body["signature"]["signed_by"] == str(PH_STAFF)
    rows = await note_versions(app, note_id)
    assert len(rows) == 1
    assert SignedContent.model_validate(rows[0].content) == expected
    assert rows[0].content_hash == content_hash(expected)
    assert rows[0].signed_by == PH_STAFF
    assert "ai_text" not in str(rows[0].content)


@pytest.mark.asyncio
async def test_removed_lines_are_not_in_the_signed_content(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    await sign_in(client, PH_STAFF)
    note_id = await make_draft(app, client)
    await client.patch(line_url(note_id, "e1-A2"), json={"action": "remove"}, headers=V1)
    for version, line_id in ((2, "e1-F"), (3, "e1-D2")):
        await client.patch(
            line_url(note_id, line_id), json={"action": "confirm"}, headers=ifm(version)
        )
    response = await client.post(url(note_id, "/sign"), json=SIGN, headers=ifm(4))
    assert response.status_code == 200, response.text
    [row] = await note_versions(app, note_id)
    lines = [
        line["id"]
        for entry in row.content["entries"]
        for line in [entry["focus"], *entry["data"], *entry["action"], *entry["response"]]
    ]
    assert "e1-A2" not in lines
    assert "Physician notified." not in str(row.content)


@pytest.mark.asyncio
async def test_another_nurse_of_the_facility_may_sign_and_is_named(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    await sign_in(client, PH_STAFF)
    note_id = await make_draft(app, client)
    confirmed = await confirm_flagged(client, note_id)
    await sign_in(client, PH_HEAD)
    response = await client.post(
        url(note_id, "/sign"), json=SIGN, headers=ifm(confirmed.json()["version"])
    )
    assert response.status_code == 200
    assert response.json()["signature"]["signed_by"] == str(PH_HEAD)


@pytest.mark.asyncio
async def test_signed_note_rejects_edits_with_409(app: FastAPI, client: httpx.AsyncClient) -> None:
    await finished_note_rejects_every_change(app, client, "sign")


@pytest.mark.asyncio
async def test_discarded_note_rejects_edits_with_409(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    await finished_note_rejects_every_change(app, client, "discard")


async def finished_note_rejects_every_change(
    app: FastAPI, client: httpx.AsyncClient, end: str
) -> None:
    await sign_in(client, PH_STAFF)
    note_id = await make_draft(app, client)
    confirmed = await confirm_flagged(client, note_id)
    version = confirmed.json()["version"]
    finished = await client.post(url(note_id, f"/{end}"), json=SIGN, headers=ifm(version))
    assert finished.status_code == 200, finished.text
    assert finished.json()["status"] == ("signed" if end == "sign" else "discarded")
    current = finished.json()["version"]
    # Locked wins over stale: a stale If-Match on a finished note is still 409.
    for header in (ifm(current), V1):
        for method, tail, body in (
            ("PATCH", "/lines/e1-D2", {"action": "remove"}),
            ("POST", "/sign", SIGN),
            ("POST", "/discard", None),
        ):
            response = await client.request(method, url(note_id, tail), json=body, headers=header)
            assert response.status_code == 409, (method, tail, response.text)
            assert response.json()["code"] == "note_locked"
    assert (await client.get(url(note_id))).json()["version"] == current


@pytest.mark.asyncio
async def test_discarded_draft_never_reaches_the_record(
    app: FastAPI, client: httpx.AsyncClient, clock: MutableClock
) -> None:
    await sign_in(client, PH_STAFF)
    note_id = await make_draft(app, client)
    response = await client.post(url(note_id, "/discard"), headers=V1)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "discarded"
    assert body["discard"] == {
        "discarded_by": str(PH_STAFF),
        "discarded_at": clock.now().isoformat().replace("+00:00", "Z"),
    }
    assert body["signature"] is None
    assert response.headers["etag"] == '"v2"'
    assert await note_versions(app, note_id) == []
    async with app.state.engine.begin() as conn:
        total = await conn.execute(select(func.count()).select_from(tables.note_version))
    assert total.scalar_one() == 0
    stored = await app.state.notes.get_note(note_id)
    assert stored.status is NoteStatus.DISCARDED
    assert stored.signature is None


@pytest.mark.asyncio
async def test_a_note_of_another_facility_is_404(app: FastAPI, client: httpx.AsyncClient) -> None:
    await sign_in(client, PH_STAFF)
    note_id = await make_draft(app, client)
    await sign_in(client, US_STAFF)
    # Not found comes before a stale or missing If-Match, so the id is never confirmed.
    for method, tail, body in (
        ("GET", "", None),
        ("PATCH", "/lines/e1-D2", {"action": "confirm"}),
        ("POST", "/sign", SIGN),
        ("POST", "/discard", None),
    ):
        response = await client.request(method, url(note_id, tail), json=body, headers=V1)
        assert response.status_code == 404, (method, tail)
        assert response.json()["code"] == "not_found"
    assert (await app.state.notes.get_note(note_id)).version == 1


@pytest.mark.asyncio
async def test_an_unknown_note_is_404(client: httpx.AsyncClient) -> None:
    await sign_in(client, PH_STAFF)
    missing = UUID("00000000-0000-4000-8000-0000000000ff")
    assert (await client.get(url(missing))).status_code == 404
    response = await client.post(url(missing, "/sign"), json=SIGN, headers=V1)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_the_admin_and_the_signed_out_are_refused(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    await sign_in(client, PH_STAFF)
    note_id = await make_draft(app, client)
    requests = (
        ("GET", "", None),
        ("PATCH", "/lines/e1-D2", {"action": "confirm"}),
        ("POST", "/sign", SIGN),
        ("POST", "/discard", None),
    )
    assert (await client.delete("/api/v1/session")).status_code == 204
    for method, tail, body in requests:
        response = await client.request(method, url(note_id, tail), json=body, headers=V1)
        assert response.status_code == 401, (method, tail)
    await sign_in(client, ADMIN)
    for method, tail, body in requests:
        response = await client.request(method, url(note_id, tail), json=body, headers=V1)
        assert response.status_code == 403, (method, tail)
        assert response.json()["code"] == "forbidden"
    assert (await app.state.notes.get_note(note_id)).version == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [{"action": "approve"}, {"action": "edit", "text": "HR\u0000 112"}, {"action": "edit"}],
)
async def test_a_malformed_line_action_is_422(
    app: FastAPI, client: httpx.AsyncClient, body: dict[str, str]
) -> None:
    await sign_in(client, PH_STAFF)
    note_id = await make_draft(app, client)
    response = await client.patch(line_url(note_id, "e1-D2"), json=body, headers=V1)
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"
    assert "HR" not in response.text
    assert (await client.get(url(note_id))).json()["version"] == 1


WRONG_PIN = {"pin": "864209"}


@pytest.mark.asyncio
async def test_sign_needs_the_right_pin(app: FastAPI, client: httpx.AsyncClient) -> None:
    await sign_in(client, PH_STAFF)
    note_id = await make_draft(app, client)

    # The PIN is checked after If-Match and before the review check: this draft still has
    # lines that need her, yet a wrong PIN is 403 (not 409), and a stale one is 412 first.
    wrong = await client.post(url(note_id, "/sign"), json=WRONG_PIN, headers=V1)
    stale = await client.post(url(note_id, "/sign"), json=WRONG_PIN, headers=ifm(9))
    assert (wrong.status_code, wrong.json()["code"], wrong.json()["tries_left"]) == (
        403,
        "pin_wrong",
        4,
    )
    assert (stale.status_code, stale.json()["code"]) == (412, "stale_version")
    assert (await client.get(url(note_id))).json()["status"] == "draft"
    unreviewed = await client.post(url(note_id, "/sign"), json=SIGN, headers=V1)
    assert (unreviewed.status_code, unreviewed.json()["code"]) == (409, "review_incomplete")

    confirmed = await confirm_flagged(client, note_id)
    version = confirmed.json()["version"]
    refused = await client.post(url(note_id, "/sign"), json=WRONG_PIN, headers=ifm(version))
    assert (refused.status_code, refused.json()["tries_left"]) == (403, 4)  # the right one cleared
    signed = await client.post(url(note_id, "/sign"), json=SIGN, headers=ifm(version))
    assert signed.status_code == 200, signed.text
    assert signed.json()["status"] == "signed"


@pytest.mark.asyncio
async def test_wrong_pin_on_sign_counts_toward_the_lock(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    await sign_in(client, PH_STAFF)
    note_id = await make_draft(app, client)
    version = (await confirm_flagged(client, note_id)).json()["version"]

    answers = [
        await client.post(url(note_id, "/sign"), json=WRONG_PIN, headers=ifm(version))
        for _ in range(5)
    ]

    assert [a.status_code for a in answers] == [403, 403, 403, 403, 401]
    assert [a.json().get("tries_left") for a in answers[:4]] == [4, 3, 2, 1]
    assert "max-age=0" in answers[4].headers["set-cookie"].lower()
    assert (await client.get(url(note_id))).status_code == 401  # the session ended
    async with client_for(app) as other:  # a fresh session of hers still signs it
        await sign_in(other, PH_STAFF)
        signed = await other.post(url(note_id, "/sign"), json=SIGN, headers=ifm(version))
        assert signed.status_code == 200, signed.text
