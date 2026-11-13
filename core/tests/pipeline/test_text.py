"""Matching a quote against the nurse's note, mapped back to the characters she typed."""

from hypothesis import given
from hypothesis import strategies as st
from nursing_core.demo import load_demo_cases
from nursing_core.domain.notes import Span
from nursing_core.pipeline.text import find_span, prepare


def test_span_after_emoji_counts_code_points() -> None:
    plain = prepare("pt had chest pain")
    with_emoji = prepare("\U0001f642pt had chest pain")
    base = find_span(plain, "chest pain")
    shifted = find_span(with_emoji, "chest pain")
    assert base is not None
    assert shifted is not None
    assert shifted == Span(start=base.start + 1, end=base.end + 1)
    assert with_emoji.raw[shifted.start : shifted.end] == "chest pain"


def test_quote_found_through_spacing_case_and_quotes() -> None:
    raw = "Pt said \u201cI\u2019m  DIZZY\u201d and\u00a0felt\nweak."
    span = find_span(prepare(raw), "i'm dizzy\" and felt weak")
    assert span is not None
    assert raw[span.start : span.end] == "I\u2019m  DIZZY\u201d and\u00a0felt\nweak"


def test_expanding_characters_point_at_their_raw_code_point() -> None:
    note = prepare("Gro\u00dfe \ufb01ber")
    assert note.text == "grosse fiber"
    span = find_span(note, "fiber")
    assert span == Span(start=6, end=10)


def test_whitespace_run_is_one_space_at_its_first_code_point() -> None:
    note = prepare(" a \t\n b")
    assert note.text == " a b"
    assert note.origin == [0, 1, 2, 6]


def test_quote_not_in_note_is_none() -> None:
    note = prepare("BP 120/80, calm")
    assert find_span(note, "temp 38") is None
    assert find_span(note, "") is None
    assert find_span(note, " \n\t ") is None


@given(st.text())
def test_origin_is_increasing_and_in_range(raw: str) -> None:
    note = prepare(raw)
    assert len(note.origin) == len(note.text)
    assert note.origin == sorted(note.origin)
    assert all(0 <= index < len(raw) for index in note.origin)


def test_demo_quotes_found_at_their_expected_spans() -> None:
    checked = 0
    for case in load_demo_cases():
        note = prepare(case.rough_note.text)
        for line in case.expected_draft.lines():
            for quote in line.source_quotes:
                assert find_span(note, quote.text) == quote.span
                checked += 1
    assert checked > 0


def test_quote_inside_a_longer_word_is_not_found() -> None:
    assert find_span(prepare("pt unresponsive to voice"), "responsive") is None
    assert find_span(prepare("pt afebrile"), "febrile") is None
    assert find_span(prepare("no painkillers given"), "no pain") is None
    assert find_span(prepare("hypo"), "hypo") == Span(start=0, end=4)


def test_number_inside_a_longer_number_is_not_found() -> None:
    assert find_span(prepare("HR 120"), "HR 12") is None
    assert find_span(prepare("T 37.8"), "7.8") is None


def test_letters_next_to_digits_still_match() -> None:
    assert find_span(prepare("BP120/80 calm"), "120/80") == Span(start=2, end=8)
    assert find_span(prepare("D5LR 1L"), "D5") == Span(start=0, end=2)


def test_later_whole_occurrence_is_found_after_a_rejected_one() -> None:
    raw = "afebrile at 2am, febrile at 4am"
    span = find_span(prepare(raw), "febrile")
    assert span == Span(start=17, end=24)


def test_first_occurrence_wins() -> None:
    assert find_span(prepare("pain now, pain later"), "pain") == Span(start=0, end=4)


def test_quote_whitespace_is_stripped() -> None:
    assert find_span(prepare("has chest pain."), " chest pain\n") == Span(start=4, end=14)
