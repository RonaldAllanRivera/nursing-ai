"""The missing-items checklist: what the chart expects that this shift's notes don't mention."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from hypothesis import given
from hypothesis import strategies as st
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


def due_alpha_bravo() -> PatientContext:
    due = NOW - timedelta(hours=1)
    return context(allergies=[], medicines=[medicine("Alpha", due), medicine("Bravo", due)])


def test_another_medicines_action_word_does_not_clear_a_due_medicine() -> None:
    for note in (
        "Alpha given, bravo due 0600",
        "Pt refused breakfast, bravo due",
        "Bravo due.Alpha given.",
        "Alpha given\uff0c bravo due",
        "Alpha given\uff1b bravo due",
    ):
        alpha, bravo = missing_items_checklist(due_alpha_bravo(), [note], NOW)
        assert not alpha.missing or "breakfast" in note, note
        assert bravo.missing, note
        assert bravo.note_span is None, note


def test_medicine_and_action_word_in_one_clause_clear_it() -> None:
    ctx = context(allergies=[], medicines=[medicine("Alpha", NOW - timedelta(hours=1))])
    assert not missing_items_checklist(ctx, ["Alpha 0.5 mg given"], NOW)[0].missing
    assert not missing_items_checklist(ctx, ["Pt refused alpha"], NOW)[0].missing
    assert missing_items_checklist(ctx, ["Alpha 40 mg SC, given at 0900"], NOW)[0].missing


def test_medicine_note_span_is_the_earliest_whole_word_alias_in_the_current_note() -> None:
    ctx = context(
        allergies=[],
        medicines=[medicine("Alpha", NOW - timedelta(hours=1), "alpha", "alpha tab", "al")],
    )
    current = "Pt had Alpha tab given. Alpha again."
    item = missing_items_checklist(ctx, ["Alpha given."], NOW)[0]
    assert item.note_span == Span(start=0, end=5)
    item = missing_items_checklist(ctx, ["Alpha given.", current], NOW)[0]
    assert item.note_span == Span(start=7, end=16)
    assert current[7:16] == "Alpha tab"


def test_missing_medicine_named_in_the_current_note_has_no_span() -> None:
    ctx = context(allergies=[], medicines=[medicine("Alpha", NOW - timedelta(hours=1))])
    item = missing_items_checklist(ctx, ["Alpha due soon."], NOW)[0]
    assert item.missing
    assert item.note_span is None


def test_a_combining_mark_makes_the_letter_part_of_a_longer_word() -> None:
    ctx = context(allergies=[], lines=[line("Cafe tube", "cafe")])
    assert missing_items_checklist(ctx, ["café tube"], NOW)[0].missing
    assert missing_items_checklist(ctx, ["xcafe"], NOW)[0].missing
    assert not missing_items_checklist(ctx, ["cafe tube"], NOW)[0].missing


def test_dizzy_word_and_safety_phrase_in_earlier_notes_count() -> None:
    ctx = context(allergies=[], fall_risk=LOW)
    flagged = missing_items_checklist(ctx, ["Pt dizzy.", "Pt resting."], NOW)
    assert [(i.rule, i.missing) for i in flagged] == [(ChecklistRule.FALL_RISK, True)]
    cleared = missing_items_checklist(ctx, ["Pt dizzy. Bed alarm on.", "Pt resting."], NOW)
    assert [(i.rule, i.missing, i.note_span) for i in cleared] == [
        (ChecklistRule.FALL_RISK, False, None)
    ]


def test_due_time_is_compared_as_an_instant_across_timezones() -> None:
    plus8 = timezone(timedelta(hours=8))
    due = medicine("Alpha", datetime(2026, 3, 4, 17, 30, tzinfo=plus8))
    later = medicine("Alpha", datetime(2026, 3, 4, 18, 30, tzinfo=plus8))
    assert len(missing_items_checklist(context(allergies=[], medicines=[due]), ["x"], NOW)) == 1
    assert missing_items_checklist(context(allergies=[], medicines=[later]), ["x"], NOW) == []


def test_taglish_and_other_action_words_clear_a_due_medicine() -> None:
    ctx = context(allergies=[], medicines=[medicine("Alpha", NOW - timedelta(hours=1))])
    for note in ("Alpha on hold", "Alpha binigay", "Alpha ibinigay", "Alpha tumanggi",
                 "Alpha administered", "Alpha withheld", "Alpha declined"):  # fmt: skip
        assert not missing_items_checklist(ctx, [note], NOW)[0].missing, note


def test_more_safety_phrases_clear_fall_risk() -> None:
    for phrase in ("Bed in low position", "Fall precautions", "fall precaution", "siderails up",
                   "call bell within reach"):  # fmt: skip
        items = missing_items_checklist(context(allergies=[], fall_risk=HIGH), [phrase], NOW)
        assert [i.missing for i in items] == [False], phrase


def test_a_recorded_allergy_list_is_not_flagged() -> None:
    assert missing_items_checklist(context(allergies=["Zyxquil"]), ["x"], NOW) == []


def one_due_medicine() -> PatientContext:
    return context(allergies=[], medicines=[medicine("Cefuroxime", NOW - timedelta(hours=1))])


def test_more_separators_end_a_clause_so_another_medicines_word_does_not_clear_it() -> None:
    for note in (
        "Paracetamol given… cefuroxime due",
        "Paracetamol given…cefuroxime due",
        "Cefuroxime due? Paracetamol given.",
        "Cefuroxime due! Paracetamol given",
        "Cefuroxime: due. Paracetamol: given",
        "Cefuroxime due - Paracetamol given",
        "Cefuroxime due / Paracetamol given",
        "Cefuroxime due \u2013 Paracetamol given",
        '"Cefuroxime due." Paracetamol given',
        "(Cefuroxime due.) Paracetamol given.",
        "Cefuroxime due。Paracetamol given",
        "Cefuroxime due、Paracetamol given",
        "Cefuroxime due\uff1f Paracetamol given",
        "Cefuroxime due\u203c Paracetamol given",
        "Cefuroxime due.Paracetamol given.",
        "Paracetamol given: cefuroxime due",
    ):
        item = missing_items_checklist(one_due_medicine(), [note], NOW)[0]
        assert item.missing, note
        assert item.note_span is None, note


def test_everyday_wording_does_not_split_a_clause() -> None:
    ctx = context(
        allergies=[],
        medicines=[
            medicine("Heparin", NOW - timedelta(hours=1)),
            medicine("Paracetamol", NOW - timedelta(hours=1)),
        ],
    )
    for note in (
        "Heparin 5,000 units given. Paracetamol 500mg p.o. given",
        "Heparin 5,000 units given, Paracetamol 500mg i.v. given",
        "Heparin 5,000 units given, Paracetamol b.i.d. given",
        "Heparin 5,000 units given, Paracetamol given at 6 a.m.",
        "Heparin 5,000 units given, Paracetamol 0.5 g given",
        "Heparin 5,000 units given, Paracetamol given re-check",
    ):
        assert [i.missing for i in missing_items_checklist(ctx, [note], NOW)] == [False, False], (
            note
        )


def test_an_emoji_variation_selector_does_not_hide_a_word() -> None:
    for note in ("⚠️dizzy", "❗️nahihilo pt"):
        items = missing_items_checklist(context(allergies=[], fall_risk=LOW), [note], NOW)
        assert [(i.rule, i.missing) for i in items] == [(ChecklistRule.FALL_RISK, True)], note
    ctx = context(allergies=[], medicines=[medicine("Paracetamol", NOW - timedelta(hours=1))])
    note = "✅️Paracetamol given"
    assert not missing_items_checklist(ctx, [note], NOW)[0].missing


def test_a_mark_on_a_letter_still_joins_the_word_either_side() -> None:
    ctx = context(allergies=[], lines=[line("Cafe tube", "cafe")])
    assert missing_items_checklist(ctx, ["xécafe"], NOW)[0].missing
    assert missing_items_checklist(ctx, ["café"], NOW)[0].missing
    assert missing_items_checklist(ctx, ["cafe️ tube"], NOW)[0].missing


def test_a_full_stop_glued_to_a_letter_ends_a_clause_unless_one_letter_precedes_it() -> None:
    for note in (
        "Paracetamol given...cefuroxime due",
        "Paracetamol given..cefuroxime due",
        "Cefuroxime due 0800.Paracetamol given",
        "1.Cefuroxime due 2.Paracetamol given",
        "Cefuroxime due (0800).Paracetamol given",
        "Cefuroxime due x2.Paracetamol given",
        "(Cefuroxime due.)Paracetamol given",
    ):
        assert missing_items_checklist(one_due_medicine(), [note], NOW)[0].missing, note


def test_one_letter_before_a_glued_full_stop_keeps_the_clause_whole() -> None:
    ctx = context(allergies=[], medicines=[medicine("Paracetamol", NOW - timedelta(hours=1))])
    for note in ("Paracetamol 500mg p.o.given", "Paracetamol c.given", "Paracetamol 0.5 given"):
        assert not missing_items_checklist(ctx, [note], NOW)[0].missing, note


def test_a_one_letter_word_then_a_full_stop_and_a_space_still_splits() -> None:
    note = "Cefuroxime due c. Paracetamol given"
    assert missing_items_checklist(one_due_medicine(), [note], NOW)[0].missing


def test_an_abbreviation_before_a_capital_letter_ends_the_clause() -> None:
    for note in (
        "Cefuroxime due 8 a.m. Paracetamol given",
        "Cefuroxime due p.o. Paracetamol given",
    ):
        assert missing_items_checklist(one_due_medicine(), [note], NOW)[0].missing, note
    ctx = context(allergies=[], medicines=[medicine("Paracetamol", NOW - timedelta(hours=1))])
    assert not missing_items_checklist(ctx, ["Paracetamol 500mg p.o. given"], NOW)[0].missing
    assert missing_items_checklist(ctx, ["Paracetamol p.o. Given at 0900"], NOW)[0].missing


def test_dash_runs_bars_bullets_and_arrows_end_a_clause() -> None:
    for note in (
        "Cefuroxime due -- Paracetamol given",
        "Cefuroxime due \u2013\u2013 Paracetamol given",
        "Cefuroxime due\u2014Paracetamol given",
        "Cefuroxime due\u2013Paracetamol given",
        "Cefuroxime due | Paracetamol given",
        "Cefuroxime due \u2022 Paracetamol given",
        "Cefuroxime due\u2192Paracetamol given",
        "Cefuroxime due -> Paracetamol given",
    ):
        assert missing_items_checklist(one_due_medicine(), [note], NOW)[0].missing, note


def test_an_en_dash_between_digits_is_a_range_not_a_clause_end() -> None:
    ctx = context(allergies=[], medicines=[medicine("Paracetamol", NOW - timedelta(hours=1))])
    assert not missing_items_checklist(ctx, ["Paracetamol 2\u20133 tabs given"], NOW)[0].missing


def test_a_full_stop_before_a_run_of_closers_ends_a_clause() -> None:
    for note in (
        'Cefuroxime "due.") Paracetamol given',
        "Cefuroxime (due\uff0e\uff09 Paracetamol given",
        "(Cefuroxime due.\u201d) Paracetamol given",
    ):
        assert missing_items_checklist(one_due_medicine(), [note], NOW)[0].missing, note


def test_wording_that_says_a_medicine_is_not_given_yet_does_not_clear_it() -> None:
    for note in (
        "Cefuroxime not yet given, pt NPO",
        "Cefuroxime to be given at 1400",
        "Cefuroxime will be given later",
        "Cefuroxime not given",
        "Cefuroxime hindi pa binigay",
        "Cefuroxime di pa ibinigay",
        "Cefuroxime wala pa binigay",
        "CEFUROXIME NOT GIVEN",
        "Hindi binigay ang Cefuroxime",
        "Cefuroxime not given due to NPO",
    ):
        assert missing_items_checklist(one_due_medicine(), [note], NOW)[0].missing, note


def test_a_not_yet_word_after_the_action_word_or_in_another_clause_does_not_count() -> None:
    for note in (
        "Cefuroxime given, pt not dizzy",
        "Cefuroxime given not late",
        "Cefuroxime held, not given",
        "Cefuroxime taken to bed 4 and given",
        "Cefuroxime given. Next dose to be given at 2200",
    ):
        assert not missing_items_checklist(one_due_medicine(), [note], NOW)[0].missing, note


def test_a_folded_en_dash_ends_a_clause() -> None:
    note = "Cefuroxime due \ufe32 Paracetamol given"
    assert missing_items_checklist(one_due_medicine(), [note], NOW)[0].missing


def test_one_letter_after_a_digit_before_a_glued_full_stop_ends_the_clause() -> None:
    for note in (
        "Cefuroxime due 1g.Paracetamol given",
        "Cefuroxime due q8h.Paracetamol given",
        "Cefuroxime due 2L.Paracetamol given",
        "Cefuroxime due 0800H.Paracetamol given",
    ):
        assert missing_items_checklist(one_due_medicine(), [note], NOW)[0].missing, note
    ctx = context(allergies=[], medicines=[medicine("Paracetamol", NOW - timedelta(hours=1))])
    for note in ("Paracetamol p.o.given", "Paracetamol i.v.given", "Paracetamol c.given"):
        assert not missing_items_checklist(ctx, [note], NOW)[0].missing, note


def test_more_dizzy_and_confused_words_bring_in_fall_risk() -> None:
    for note in ("Pt light headed.", "Lightheadedness noted.", "Disorientation at 0200."):
        items = missing_items_checklist(context(allergies=[], fall_risk=LOW), [note], NOW)
        assert [(i.rule, i.missing) for i in items] == [(ChecklistRule.FALL_RISK, True)], note


def test_a_full_stop_before_a_curly_or_corner_bracket_ends_a_clause() -> None:
    for note in (
        "{Cefuroxime due.} Paracetamol given",
        "\u300cCefuroxime due.\u300dParacetamol given",
        "\u300eCefuroxime due.\u300f Paracetamol given",
        "Cefuroxime (due.\uff5d Paracetamol given",
    ):
        assert missing_items_checklist(one_due_medicine(), [note], NOW)[0].missing, note


_CHECKLIST_PIECES = st.one_of(
    st.text(),
    st.sampled_from(
        ["Cefuroxime", "given", "not", "hindi pa", "to be", " ", ".", ",", "\u2013", "\ufe32",
         "p.o.", "1g", "\u300d", "}", "\n", "-", " -> ", "dizzy", "bed alarm on", "foley", "CBC"]
    ),
)  # fmt: skip


@given(st.lists(st.lists(_CHECKLIST_PIECES, max_size=8).map("".join), min_size=1, max_size=3))
def test_the_checklist_and_its_clause_ends_never_raise_on_arbitrary_text(notes: list[str]) -> None:
    ctx = context(
        allergies=None,
        lines=[line("Foley", "foley")],
        medicines=[medicine("Cefuroxime", NOW - timedelta(hours=1))],
        tests=[PendingTest(name="CBC", sent_at=None, aliases=["cbc"])],
        fall_risk=HIGH,
    )
    items = missing_items_checklist(ctx, notes, NOW)
    assert [item.rule for item in items] == [
        ChecklistRule.ALLERGIES,
        ChecklistRule.LINE_OR_TUBE,
        ChecklistRule.MEDICINE_DUE,
        ChecklistRule.PENDING_TEST,
        ChecklistRule.FALL_RISK,
    ]
