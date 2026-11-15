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


def test_quote_inside_a_hyphenated_word_is_not_found() -> None:
    assert find_span(prepare("pt non-responsive"), "responsive") is None
    assert find_span(prepare("non-responsive pt"), "non") is None
    assert find_span(prepare("BP 90/60 and 2-3 times"), "2") == Span(start=13, end=14)
    assert find_span(prepare("pt - responsive"), "responsive") == Span(start=5, end=15)


def test_number_inside_a_decimal_is_not_found() -> None:
    assert find_span(prepare("T 37.8"), "T 37") is None
    assert find_span(prepare("37.8 HR 90"), "8 HR") is None
    assert find_span(prepare("T 37.8"), "37.8") == Span(start=2, end=6)
    assert find_span(prepare("seen at 3. 4 more"), "3") == Span(start=8, end=9)


def test_combining_mark_continues_the_word() -> None:
    assert find_span(prepare("mañana"), "man") is None
    assert find_span(prepare("mañana"), "̃ana") is None
    assert find_span(prepare("mañana"), "mañana") == Span(start=0, end=7)


def test_combining_mark_before_the_quote_continues_the_word() -> None:
    decomposed = "mañana"
    assert find_span(prepare(decomposed), "ana") is None
    assert find_span(prepare(decomposed), "mañ") is None
    assert find_span(prepare(decomposed), "mañana") == Span(start=0, end=7)
    assert find_span(prepare("pt mañana ok"), "ok") == Span(start=11, end=13)


HY = chr(0x2010)  # hyphen
NB = chr(0x2011)  # non-breaking hyphen


def test_unicode_hyphen_continues_the_word() -> None:
    assert find_span(prepare(f"non{HY}responsive"), "responsive") is None
    assert find_span(prepare(f"non{NB}responsive"), "responsive") is None
    assert find_span(prepare(f"non{NB}responsive"), "non") is None
    assert find_span(prepare(f"pt {HY} responsive"), "responsive") == Span(start=5, end=15)


ACUTE = chr(0x301)  # combining acute accent
WARNING = "⚠️"  # warning sign drawn as an emoji (variation selector 16)
HEART = "❤️"  # red heart drawn as an emoji (variation selector 16)


def test_combining_mark_before_a_hyphen_continues_the_word() -> None:
    decomposed = f"cafe{ACUTE}-noir"
    assert find_span(prepare(decomposed), f"cafe{ACUTE}") is None
    assert find_span(prepare(decomposed), "noir") is None
    assert find_span(prepare(decomposed), "-noir") is None
    assert find_span(prepare(f"pt cafe{ACUTE} - noir"), f"cafe{ACUTE}") == Span(start=3, end=8)


def test_quote_right_after_an_emoji_with_a_variation_selector_is_found() -> None:
    note = prepare(f"{WARNING}pt had chest pain")
    assert find_span(note, "pt had chest pain") == Span(start=2, end=19)
    assert find_span(prepare(f"{HEART}HR 88"), "HR 88") == Span(start=2, end=7)
    assert find_span(prepare(f"{WARNING}HR 88"), WARNING) == Span(start=0, end=2)
    assert find_span(prepare(f"{WARNING}HR 88"), "️HR 88") == Span(start=1, end=7)


def test_quote_starting_or_ending_with_a_hyphen_inside_a_word_is_not_found() -> None:
    assert find_span(prepare("pt non-responsive"), "-responsive") is None
    assert find_span(prepare("non-responsive"), "non-") is None
    assert find_span(prepare(f"pt non{NB}responsive"), f"{NB}responsive") is None
    assert find_span(prepare("pt - responsive"), "- responsive") == Span(start=3, end=15)
    assert find_span(prepare("seen non- today"), "non-") == Span(start=5, end=9)


def test_number_after_a_leading_decimal_point_is_not_found() -> None:
    assert find_span(prepare("give .5 mg"), "5 mg") is None
    assert find_span(prepare("seen at 3. 4 more"), "4 more") == Span(start=11, end=17)
    assert find_span(prepare("T 37.5"), ".5") is None


def test_quote_ending_in_a_dot_inside_a_decimal_is_not_found() -> None:
    assert find_span(prepare("HR 90.5"), "HR 90.") is None
    assert find_span(prepare("T 37.9. nagsuk"), "T 37.9") == Span(start=0, end=6)
    assert find_span(prepare("T 37.9. nagsuk"), "T 37.9.") == Span(start=0, end=7)
