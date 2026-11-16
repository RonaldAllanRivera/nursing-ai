"""The recordings committed in the repo still replay: each demo request still matches one."""

from pathlib import Path

import pytest
from nursing_core.demo import DemoCase, load_demo_cases
from nursing_core.providers.replay import RECORDINGS_DIR, ReplayProvider

from .helpers import STAFF_NURSE, MutableClock, client_for, post_note, running_app, sign_in

CASES = load_demo_cases()
FOLDER: Path = RECORDINGS_DIR
RECORDED = any(FOLDER.glob("*.json"))


@pytest.mark.skipif(not RECORDED, reason="no recordings are committed yet (make record-replays)")
@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=[c.key for c in CASES])
async def test_each_demo_note_drafts_from_the_committed_recordings(
    case: DemoCase, database_url: str
) -> None:
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
        posted = await post_note(
            client,
            case.patient_id,
            case.rough_note.text,
            key=case.key,
        )
        assert posted.status_code == 202, posted.text
        await app.state.queue.drain()
        job = (await client.get(f"/api/v1/draft-jobs/{posted.json()['id']}")).json()
    assert job["status"] == "succeeded", job
