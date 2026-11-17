"""The web app's mock data is generated from the demo cases, and the committed copy can't drift."""

from pathlib import Path

from nursing_api.demo_export import build, render
from nursing_core.demo import DEMO_PERSONAS, load_demo_cases


def test_committed_demo_api_matches_cases(repo_root: Path) -> None:
    committed = (repo_root / "web" / "src" / "mocks" / "demo-api.ts").read_text(encoding="utf-8")
    assert committed == render()


def test_rendered_file_says_it_is_generated() -> None:
    head = render().splitlines()[0]
    assert "Generated" in head
    assert "make openapi" in head


def test_each_patient_posts_to_a_job_that_leads_to_its_demo_note() -> None:
    data = build()
    for case in load_demo_cases():
        job = data.jobs[str(data.job_for_patient[str(case.patient_id)])]
        assert job.status == "succeeded"
        note = data.notes[str(job.note_id)]
        assert note.patient.id == case.patient_id
        assert note.rough_note.text == case.rough_note.text
        assert note.draft == case.expected_draft
        assert note.status == "draft"
        assert note.version == 1


def test_patients_start_the_shift_with_no_notes() -> None:
    assert all(not detail.notes for detail in build().patient_details.values())


def test_every_persona_has_a_session_and_the_admin_has_no_shift() -> None:
    data = build()
    assert sorted(data.sessions) == sorted(str(p.id) for p in DEMO_PERSONAS)
    admin = next(s for s in data.sessions.values() if s.role == "admin")
    assert admin.facility_key is None
    assert admin.shift is None
    nurses = [s for s in data.sessions.values() if s.role != "admin"]
    assert all(s.shift is not None for s in nurses)


def test_patients_are_listed_by_facility() -> None:
    patients = build().patients
    assert sorted(patients) == ["ph-demo", "us-demo"]
    assert [p.display_name for p in patients["ph-demo"]] == ["Demo patient A", "Demo patient B"]
    assert [p.display_name for p in patients["us-demo"]] == ["Demo patient C"]


def test_each_facilitys_nurses_and_cases_share_one_shift() -> None:
    data = build()
    for case in load_demo_cases():
        nurses = [
            session
            for session in data.sessions.values()
            if session.facility_key == case.facility_key
        ]
        assert nurses
        assert all(session.shift == case.rough_note.shift for session in nurses)
        assert data.patient_details[str(case.patient_id)].shift == case.rough_note.shift
        assert case.rough_note.shift in data.facilities[case.facility_key].shift_choices


def test_each_demo_patient_offers_its_demo_note() -> None:
    # Replay knows only the demo notes, so the mock offers "Use the demo note" for each.
    details = build().patient_details
    for case in load_demo_cases():
        assert details[str(case.patient_id)].demo_note == case.rough_note.text


def test_mock_sessions_are_open_persona_sessions_with_a_csrf_token() -> None:
    for session in build().sessions.values():
        assert (session.kind, session.gate, session.idle_lock_seconds) == ("persona", "open", 300)
        assert session.csrf_token


def test_mock_jobs_say_whether_they_can_be_tried_again() -> None:
    assert all(job.retryable is False for job in build().jobs.values())
