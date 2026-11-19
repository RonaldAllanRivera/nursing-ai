"""Personas (public PIN) and invited people never see or act on each other's notes."""

from typing import cast

import httpx
import pytest
from fastapi import FastAPI
from nursing_core.demo import DEMO_PIN

from .helpers import PH_STAFF, add_invited_nurse, client_for, sign_in
from .test_notes import PH_CASE, ifm, line_url, make_draft, url


async def two_sides(app: FastAPI, persona: httpx.AsyncClient) -> httpx.AsyncClient:
    """The persona's client is signed in as PH staff; returns a client of an invited nurse of the
    same facility."""
    await sign_in(persona, PH_STAFF)
    invited = client_for(app)
    await sign_in(invited, await add_invited_nurse(app, "ph-demo"))
    return invited


async def refused_everything(client: httpx.AsyncClient, note_id: object, version: int) -> None:
    assert (await client.get(url(note_id))).status_code == 404  # type: ignore[arg-type]
    patched = await client.patch(
        line_url(note_id, "e1-F"),  # type: ignore[arg-type]
        json={"action": "confirm"},
        headers=ifm(version),
    )
    assert patched.status_code == 404
    signed = await client.post(
        url(note_id, "/sign"),  # type: ignore[arg-type]
        json={"pin": DEMO_PIN},
        headers=ifm(version),
    )
    assert signed.status_code == 404
    discarded = await client.post(
        url(note_id, "/discard"),  # type: ignore[arg-type]
        headers=ifm(version),
    )
    assert discarded.status_code == 404


async def shift_list(client: httpx.AsyncClient) -> list[object]:
    body = (await client.get(f"/api/v1/patients/{PH_CASE.patient_id}")).json()
    notes: list[object] = body["notes"]
    return notes


@pytest.mark.asyncio
async def test_a_persona_never_opens_or_changes_an_invited_nurses_note(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    invited = await two_sides(app, client)
    note_id = await make_draft(app, invited)
    version = (await invited.get(url(note_id))).json()["version"]
    await refused_everything(client, note_id, version)
    assert len(await shift_list(invited)) == 1
    assert await shift_list(client) == []
    # the note is untouched: still the invited nurse's open draft
    own = await invited.get(url(note_id))
    assert own.status_code == 200
    assert own.json()["status"] == "draft"


@pytest.mark.asyncio
async def test_an_invited_nurse_never_opens_or_changes_a_personas_note(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    invited = await two_sides(app, client)
    note_id = await make_draft(app, client)
    version = (await client.get(url(note_id))).json()["version"]
    await refused_everything(invited, note_id, version)
    assert len(await shift_list(client)) == 1
    assert await shift_list(invited) == []
    assert (await client.get(url(note_id))).json()["status"] == "draft"


async def own_job_id(owner: httpx.AsyncClient) -> str:
    """The id of the draft job behind the owner's one rough note on the shift list."""
    (entry,) = await shift_list(owner)
    assert isinstance(entry, dict)
    job = cast("dict[str, object]", entry)["job"]
    assert isinstance(job, dict)
    return str(cast("dict[str, object]", job)["id"])


@pytest.mark.asyncio
async def test_neither_side_polls_the_other_sides_draft_job(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    # The poll shows a job's status and its note's id, and may send the job again: it keeps to the
    # same side as the note routes.
    invited = await two_sides(app, client)
    await make_draft(app, invited)
    invited_job = await own_job_id(invited)
    await make_draft(app, client)
    persona_job = await own_job_id(client)
    assert (await client.get(f"/api/v1/draft-jobs/{invited_job}")).status_code == 404
    assert (await invited.get(f"/api/v1/draft-jobs/{persona_job}")).status_code == 404
    assert (await invited.get(f"/api/v1/draft-jobs/{invited_job}")).status_code == 200
    assert (await client.get(f"/api/v1/draft-jobs/{persona_job}")).status_code == 200
