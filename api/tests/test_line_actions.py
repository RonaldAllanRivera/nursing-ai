"""The four line actions as pure steps on a draft: no database, no HTTP."""

import pytest
from nursing_api.line_actions import apply_line_action
from nursing_api.problems import ActionRefused
from nursing_api.schemas import ConfirmLine, EditLine, RemoveLine, RestoreLine
from nursing_core.demo import load_demo_cases
from nursing_core.domain.errors import NotFound
from nursing_core.domain.notes import DraftLine, FdarDraft, LineReview, LineStatus
from nursing_core.domain.units import Ucum, UnitDefaults

CASE = load_demo_cases()[0]
TEXT = CASE.rough_note.text
CELSIUS = UnitDefaults(temperature=Ucum.CEL, weight=Ucum.KG, volume=Ucum.ML)
FAHRENHEIT = UnitDefaults(temperature=Ucum.DEG_F, weight=Ucum.KG, volume=Ucum.ML)
TEMPERATURE_EDIT = "Shivering at around 3 AM, temperature 37.9 °C."


def line(draft: FdarDraft, line_id: str) -> DraftLine:
    return next(found for found in draft.lines() if found.id == line_id)


def act(
    draft: FdarDraft,
    line_id: str,
    action: ConfirmLine | EditLine | RemoveLine | RestoreLine,
    units: UnitDefaults = CELSIUS,
) -> FdarDraft:
    return apply_line_action(draft, line_id, action, TEXT, units)


def test_confirm_makes_a_pending_line_confirmed_and_touches_no_other() -> None:
    draft = CASE.expected_draft
    after = act(draft, "e1-D2", ConfirmLine(action="confirm"))
    assert line(after, "e1-D2").review is LineReview.CONFIRMED
    others = [found for found in after.lines() if found.id != "e1-D2"]
    assert others == [found for found in draft.lines() if found.id != "e1-D2"]


def test_confirm_keeps_an_edited_line_edited_and_a_confirmed_line_confirmed() -> None:
    edited = act(CASE.expected_draft, "e1-D2", EditLine(action="edit", text="BP 90/60 mmHg."))
    assert act(edited, "e1-D2", ConfirmLine(action="confirm")) == edited
    confirmed = act(CASE.expected_draft, "e1-D2", ConfirmLine(action="confirm"))
    assert act(confirmed, "e1-D2", ConfirmLine(action="confirm")) == confirmed


def test_confirm_on_a_removed_line_says_to_restore_it_first() -> None:
    removed = act(CASE.expected_draft, "e1-A2", RemoveLine(action="remove"))
    with pytest.raises(ActionRefused, match="restore"):
        act(removed, "e1-A2", ConfirmLine(action="confirm"))


def test_edit_rechecks_the_line_and_counts_as_reviewed() -> None:
    after = act(CASE.expected_draft, "e1-D2", EditLine(action="edit", text="BP 90/60 mmHg."))
    edited = line(after, "e1-D2")
    assert edited.review is LineReview.EDITED
    assert edited.text == "BP 90/60 mmHg."
    assert edited.status is LineStatus.SOURCE_FOUND
    assert edited.ai_text == line(CASE.expected_draft, "e1-D2").ai_text


def test_edit_uses_the_units_it_is_given() -> None:
    edit = EditLine(action="edit", text=TEMPERATURE_EDIT)
    celsius = line(act(CASE.expected_draft, "e1-D3", edit, CELSIUS), "e1-D3")
    fahrenheit = line(act(CASE.expected_draft, "e1-D3", edit, FAHRENHEIT), "e1-D3")
    assert celsius.status is LineStatus.SOURCE_FOUND
    assert fahrenheit.status is LineStatus.NUMBER_MISMATCH


def test_edit_brings_a_removed_line_back() -> None:
    removed = act(CASE.expected_draft, "e1-A2", RemoveLine(action="remove"))
    after = act(removed, "e1-A2", EditLine(action="edit", text="Physician informed."))
    assert line(after, "e1-A2").review is LineReview.EDITED


def test_remove_marks_a_line_removed() -> None:
    after = act(CASE.expected_draft, "e1-A2", RemoveLine(action="remove"))
    assert line(after, "e1-A2").review is LineReview.REMOVED
    assert act(after, "e1-A2", RemoveLine(action="remove")) == after


def test_remove_refuses_a_focus_line() -> None:
    with pytest.raises(ActionRefused, match="focus"):
        act(CASE.expected_draft, "e1-F", RemoveLine(action="remove"))


def test_restore_puts_the_ai_text_back_as_pending() -> None:
    edited = act(CASE.expected_draft, "e1-D2", EditLine(action="edit", text="BP 90/60 mmHg."))
    restored = line(act(edited, "e1-D2", RestoreLine(action="restore")), "e1-D2")
    original = line(CASE.expected_draft, "e1-D2")
    assert restored.text == original.ai_text
    assert restored.review is LineReview.PENDING
    assert restored.status is original.status


def test_restore_brings_back_a_removed_line() -> None:
    removed = act(CASE.expected_draft, "e1-A2", RemoveLine(action="remove"))
    restored = line(act(removed, "e1-A2", RestoreLine(action="restore")), "e1-A2")
    assert restored.review is LineReview.PENDING


def test_an_unknown_line_is_not_found() -> None:
    with pytest.raises(NotFound):
        act(CASE.expected_draft, "nope", ConfirmLine(action="confirm"))
