"""The recordings committed in the repo still replay: each demo request still matches one, and the
drafts testers see from them (the live demo's `AI_MODE=replay`) keep their line statuses and
checklist."""

import json
from pathlib import Path
from typing import Any

import pytest
from nursing_core.demo import DemoCase, load_demo_cases
from nursing_core.providers.replay import RECORDINGS_DIR, ReplayProvider

from .helpers import STAFF_NURSE, MutableClock, client_for, post_note, running_app, sign_in

CASES = load_demo_cases()
FOLDER: Path = RECORDINGS_DIR
RECORDED = any(FOLDER.glob("*.json"))
NEEDS_RECORDINGS = pytest.mark.skipif(
    not RECORDED, reason="no recordings are committed yet (make record-replays)"
)


async def replayed(case: DemoCase, database_url: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """The case's note posted as its facility's staff nurse and drafted from the recordings:
    the finished job and the draft note (an empty dict when the job did not succeed)."""
    replay = ReplayProvider(FOLDER)
    clock = MutableClock()
    clock.set(case.rough_note.written_at)
    async with (
        running_app(
            database_url, clock, ai_mode="replay", provider_for=lambda _patient: replay
        ) as app,
        client_for(app) as client,
    ):
        await sign_in(client, STAFF_NURSE[case.facility_key])
        posted = await post_note(client, case.patient_id, case.rough_note.text, key=case.key)
        assert posted.status_code == 202, posted.text
        await app.state.queue.drain()
        job = (await client.get(f"/api/v1/draft-jobs/{posted.json()['id']}")).json()
        if job["status"] != "succeeded":
            return job, {}
        return job, (await client.get(f"/api/v1/notes/{job['note_id']}")).json()


def what_a_tester_sees(note: dict[str, Any]) -> dict[str, Any]:
    """Each line's id, status and number mismatches, and the checklist: what the source check
    and the missing-items rules decided about the recorded draft."""
    lines: list[str] = []
    for entry in note["draft"]["entries"]:
        for line in [entry["focus"], *entry["data"], *entry["action"], *entry["response"]]:
            mismatches = ",".join(json.dumps(m, sort_keys=True) for m in line["number_mismatches"])
            lines.append(f"{line['id']} {line['status']} [{mismatches}]")
    checklist = [
        f"{item['rule']} {item['subject']} {'missing' if item['missing'] else 'covered'}"
        for item in note["checklist"]
    ]
    return {"lines": lines, "checklist": checklist}


# What the committed recordings draft today (every line is `source_found` or `summary`; a
# mismatch list is empty). A change to the source check or the missing-items rules that moves
# any of it fails here: look at the new drafts, then update this on purpose.
SNAPSHOT: dict[str, dict[str, Any]] = {
    "demo-1": {
        "lines": [
            "e1-F summary []",
            "e1-D1 source_found []",
            "e1-D2 source_found []",
            "e1-A1 source_found []",
            "e1-R1 source_found []",
            "e2-F summary []",
            "e2-D1 source_found []",
            "e3-F summary []",
            "e3-D1 source_found []",
            "e4-F summary []",
            "e4-D1 source_found []",
        ],
        "checklist": [
            "line_or_tube IV line, left arm covered",
            "pending_test CBC missing",
            "fall_risk Fall risk missing",
        ],
    },
    "demo-2": {
        "lines": [
            "e1-F summary []",
            "e1-D1 source_found []",
            "e1-D2 source_found []",
            "e1-A1 source_found []",
            "e1-A2 source_found []",
            "e1-R1 source_found []",
            "e2-F summary []",
            "e2-D1 source_found []",
            "e2-D2 source_found []",
            "e2-A1 source_found []",
            "e2-A2 source_found []",
            "e2-A3 source_found []",
        ],
        "checklist": [
            "allergies Allergies missing",
            "line_or_tube IV heplock, left hand missing",
            "medicine_due Cefuroxime 750 mg IV missing",
        ],
    },
    "demo-3": {
        "lines": [
            "e1-F summary []",
            "e1-D1 source_found []",
            "e1-A1 source_found []",
            "e1-R1 source_found []",
            "e2-F summary []",
            "e2-D1 source_found []",
            "e2-D2 source_found []",
            "e3-F summary []",
            "e3-A1 source_found []",
            "e3-A2 source_found []",
            "e3-R1 source_found []",
            "e4-F summary []",
            "e4-D1 source_found []",
            "e4-A1 source_found []",
        ],
        "checklist": [
            "line_or_tube PIV, left forearm missing",
            "medicine_due Enoxaparin 40 mg SUBQ missing",
            "pending_test BMP missing",
            "fall_risk Fall risk covered",
        ],
    },
}


@NEEDS_RECORDINGS
@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=[c.key for c in CASES])
async def test_each_demo_note_drafts_from_the_committed_recordings(
    case: DemoCase, database_url: str
) -> None:
    job, _note = await replayed(case, database_url)
    assert job["status"] == "succeeded", job


@NEEDS_RECORDINGS
@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=[c.key for c in CASES])
async def test_the_replayed_drafts_keep_their_line_statuses_and_checklist(
    case: DemoCase, database_url: str
) -> None:
    _job, note = await replayed(case, database_url)
    assert what_a_tester_sees(note) == SNAPSHOT[case.key]
