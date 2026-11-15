"""The missing-items checklist: what the chart expects that this shift's notes don't mention."""

from datetime import UTC, datetime, timedelta

import pytest
from nursing_core.demo import load_demo_cases
from nursing_core.domain.notes import ChecklistItem, ChecklistRule, Span
from nursing_core.domain.patient import (
    FallRisk,
    LineOrTube,
    MedicineDue,
    PatientContext,
    PendingTest,
)
from nursing_core.pipeline.checklist import missing_items_checklist

NOW = datetime(2026, 3, 4, 10, 0, tzinfo=UTC)


def context(
    *,
    allergies: list[str] | None = None,
    lines: list[LineOrTube] | None = None,
    medicines: list[MedicineDue] | None = None,
    tests: list[PendingTest] | None = None,
    fall_risk: FallRisk | None = None,
    code_status: str = "Full code",
) -> PatientContext:
    return PatientContext(
        allergies=allergies,
        code_status=code_status,
        lines_tubes=lines or [],
        medicines_due=medicines or [],
        pending_tests=tests or [],
        latest_vitals=None,
        fall_risk=fall_risk,
    )


def line(description: str, *aliases: str) -> LineOrTube:
    return LineOrTube(kind="line", description=description, aliases=list(aliases))


def medicine(name: str, due_at: datetime, *aliases: str) -> MedicineDue:
    return MedicineDue(
        name=name, dose="500 mg", route="PO", due_at=due_at, aliases=list(aliases) or [name]
    )


def by_subject(items: list[ChecklistItem]) -> dict[str, ChecklistItem]:
    return {item.subject: item for item in items}


def test_allergies_flagged_only_when_not_recorded() -> None:
    items = missing_items_checklist(context(allergies=None), ["Pt resting."], NOW)
    assert items == [
        ChecklistItem(
            rule=ChecklistRule.ALLERGIES, subject="Allergies", missing=True, note_span=None
        )
    ]


def test_nkda_counts_as_recorded() -> None:
    assert missing_items_checklist(context(allergies=[]), ["Pt resting."], NOW) == []


def test_each_unmentioned_line_or_tube_flagged() -> None:
    ctx = context(
        allergies=[],
        lines=[line("IV heplock, left hand", "IV", "heplock"), line("Foley", "foley", "catheter")],
    )
    items = by_subject(missing_items_checklist(ctx, ["IV site clean."], NOW))
    assert not items["IV heplock, left hand"].missing
    assert items["Foley"].missing


def test_medicine_due_before_last_note_flagged_unless_given_held_or_refused() -> None:
    ctx = context(
        allergies=[],
        medicines=[
            medicine("Alpha", NOW - timedelta(hours=1)),
            medicine("Bravo", NOW),
            medicine("Charlie", NOW),
            medicine("Delta", NOW),
        ],
    )
    note = "Alpha given. Bravo held. Charlie refused by pt."
    items = by_subject(missing_items_checklist(ctx, [note], NOW))
    assert [i.missing for i in items.values()] == [False, False, False, True]
    assert list(items) == [
        "Alpha 500 mg PO",
        "Bravo 500 mg PO",
        "Charlie 500 mg PO",
        "Delta 500 mg PO",
    ]


def test_medicine_due_after_last_note_not_flagged() -> None:
    ctx = context(allergies=[], medicines=[medicine("Alpha", NOW + timedelta(seconds=1))])
    assert missing_items_checklist(ctx, ["Pt resting."], NOW) == []


def test_pending_test_flagged_when_not_mentioned() -> None:
    ctx = context(
        allergies=[],
        tests=[
            PendingTest(name="CBC", sent_at=None, aliases=["cbc"]),
            PendingTest(name="Urinalysis", sent_at=None, aliases=["urinalysis", "ua"]),
        ],
    )
    items = by_subject(missing_items_checklist(ctx, ["CBC sent."], NOW))
    assert not items["CBC"].missing
    assert items["Urinalysis"].missing


HIGH = FallRisk(scale="Morse", score=60, high=True)
LOW = FallRisk(scale="Morse", score=10, high=False)


def test_fall_risk_high_without_safety_measure_flagged() -> None:
    items = missing_items_checklist(context(allergies=[], fall_risk=HIGH), ["Pt resting."], NOW)
    assert items == [
        ChecklistItem(
            rule=ChecklistRule.FALL_RISK, subject="Fall risk", missing=True, note_span=None
        )
    ]


def test_low_fall_risk_without_dizziness_not_flagged() -> None:
    assert missing_items_checklist(context(allergies=[], fall_risk=LOW), ["Pt resting."], NOW) == []
    assert missing_items_checklist(context(allergies=[]), ["Pt resting."], NOW) == []


def test_newly_dizzy_without_safety_measure_flagged() -> None:
    items = missing_items_checklist(context(allergies=[], fall_risk=LOW), ["Pt nahihilo."], NOW)
    assert [(i.rule, i.missing) for i in items] == [(ChecklistRule.FALL_RISK, True)]
    confused = missing_items_checklist(context(allergies=[]), ["Pt is Confused."], NOW)
    assert [(i.rule, i.missing) for i in confused] == [(ChecklistRule.FALL_RISK, True)]


def test_safety_measure_clears_fall_risk() -> None:
    note = "Pt dizzy. Side rails   up, bed alarm on."
    items = missing_items_checklist(context(allergies=[], fall_risk=HIGH), [note], NOW)
    assert [i.missing for i in items] == [False]


def test_us_safety_words_clear_fall_risk() -> None:
    for phrase in ("Call light within reach", "non-skid socks on", "Bed in lowest position"):
        items = missing_items_checklist(context(allergies=[], fall_risk=HIGH), [phrase], NOW)
        assert [i.missing for i in items] == [False], phrase


def test_code_status_never_flagged() -> None:
    for status in ("Full code", "DNR", ""):
        ctx = context(allergies=[], code_status=status)
        assert missing_items_checklist(ctx, ["Pt resting."], NOW) == []


def test_earlier_notes_in_the_shift_count() -> None:
    ctx = context(allergies=[], lines=[line("Foley", "foley")])
    items = missing_items_checklist(ctx, ["Foley draining.", "Pt resting."], NOW)
    assert [i.missing for i in items] == [False]


def test_medicine_alias_and_given_word_must_share_a_sentence() -> None:
    ctx = context(allergies=[], medicines=[medicine("Alpha", NOW - timedelta(hours=1))])
    for note in (
        "Alpha due. Pt given water.",
        "Alpha due\nPt given water",
        "Alpha due; pt given water",
    ):
        assert missing_items_checklist(ctx, [note], NOW)[0].missing, note
    assert not missing_items_checklist(ctx, ["Alpha 0.5 mg given"], NOW)[0].missing
    assert not missing_items_checklist(ctx, ["Pt refused Alpha."], NOW)[0].missing
    assert not missing_items_checklist(ctx, ["Alpha due", "Alpha given"], NOW)[0].missing
    assert missing_items_checklist(ctx, ["Alpha due.", "Pt given water."], NOW)[0].missing


def test_alias_matches_whole_words_only() -> None:
    ctx = context(allergies=[], lines=[line("IV line", "IV")])
    assert missing_items_checklist(ctx, ["IVF running."], NOW)[0].missing
    assert not missing_items_checklist(ctx, ["iv  \n site ok"], NOW)[0].missing
    multi = context(allergies=[], lines=[line("NG tube", "ng  tube")])
    assert not missing_items_checklist(multi, ["NG\ntube ok"], NOW)[0].missing
    assert missing_items_checklist(multi, ["NG only"], NOW)[0].missing


def test_blank_alias_never_matches() -> None:
    ctx = context(allergies=[], lines=[line("Foley", " ")])
    assert missing_items_checklist(ctx, ["anything"], NOW)[0].missing


def test_note_span_only_on_cleared_items_in_the_current_note() -> None:
    ctx = context(
        allergies=[],
        lines=[line("Foley", "foley", "foley catheter"), line("IV", "iv")],
        tests=[PendingTest(name="CBC", sent_at=None, aliases=["cbc"])],
        fall_risk=HIGH,
    )
    earlier = "CBC sent."
    current = "Pt\u2019s  Foley catheter draining, foley ok. Side rails up."
    items = by_subject(missing_items_checklist(ctx, [earlier, current], NOW))
    foley = items["Foley"].note_span
    assert foley == Span(
        start=current.index("Foley"), end=current.index("Foley") + len("Foley catheter")
    )
    assert items["IV"].missing
    assert items["IV"].note_span is None
    assert not items["CBC"].missing
    assert items["CBC"].note_span is None
    fall = items["Fall risk"].note_span
    assert fall is not None
    assert current[fall.start : fall.end] == "Side rails up"


def test_items_come_in_rule_order() -> None:
    later = NOW - timedelta(hours=1)
    earlier = NOW - timedelta(hours=3)
    ctx = context(
        allergies=None,
        lines=[line("Foley", "foley"), line("IV", "iv")],
        medicines=[medicine("Late", later), medicine("Early", earlier), medicine("Same", later)],
        tests=[
            PendingTest(name="CBC", sent_at=None, aliases=["cbc"]),
            PendingTest(name="UA", sent_at=None, aliases=["ua"]),
        ],
        fall_risk=HIGH,
    )
    items = missing_items_checklist(ctx, ["x"], NOW)
    assert [i.subject for i in items] == [
        "Allergies",
        "Foley",
        "IV",
        "Early 500 mg PO",
        "Late 500 mg PO",
        "Same 500 mg PO",
        "CBC",
        "UA",
        "Fall risk",
    ]


def test_naive_last_note_at_and_no_notes_are_refused() -> None:
    with pytest.raises(ValueError, match="timezone"):
        missing_items_checklist(context(), ["x"], datetime(2026, 3, 4, 10, 0))
    with pytest.raises(ValueError, match="note"):
        missing_items_checklist(context(), [], NOW)


def test_demo_checklists_match_expected() -> None:
    for case in load_demo_cases():
        items = missing_items_checklist(
            case.context, [case.rough_note.text], case.rough_note.written_at
        )
        assert items == case.expected_checklist, case.key
