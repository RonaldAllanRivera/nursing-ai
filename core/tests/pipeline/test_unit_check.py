"""Finding numbers in a line and reading the unit written right after one."""

from nursing_core.domain.notes import Span
from nursing_core.domain.units import Ucum
from nursing_core.pipeline.unit_check import number_value, numbers_in, unit_after, unit_end_after


def _unit(text: str, number: str) -> Ucum | None:
    start = text.index(number)
    return unit_after(text, Span(start=start, end=start + len(number)))


def test_hash_after_a_number_is_pounds_but_ivf_hash_3_is_not() -> None:
    assert _unit("wt 176# today", "176") is Ucum.LB
    assert _unit("wt 176 # today", "176") is None
    assert _unit("IVF #3 running", "3") is None


def test_numbers_in_finds_decimals_and_numbers_inside_words() -> None:
    assert numbers_in("D5LR x4, SpO2 95%, BP 90/60, T 37.9") == [
        ("4", Span(start=6, end=7)),
        ("2", Span(start=12, end=13)),
        ("95", Span(start=14, end=16)),
        ("90/60", Span(start=22, end=27)),
        ("37.9", Span(start=31, end=35)),
    ]


def test_unit_after_reads_the_alias_table_with_or_without_a_space() -> None:
    cases = {
        "T 100.2F": ("100.2", Ucum.DEG_F),
        "T 100.2 °F": ("100.2", Ucum.DEG_F),
        "T 100.2 degF": ("100.2", Ucum.DEG_F),
        "T 37.4C": ("37.4", Ucum.CEL),
        "T 37.4\t°C.": ("37.4", Ucum.CEL),
        "600cc": ("600", Ucum.ML),
        "600 mL": ("600", Ucum.ML),
        "600 ml,": ("600", Ucum.ML),
        "176lb": ("176", Ucum.LB),
        "176 lbs": ("176", Ucum.LB),
        "80 kg": ("80", Ucum.KG),
    }
    for text, (number, unit) in cases.items():
        assert _unit(text, number) is unit, text


def test_c_slash_o_and_ml_per_hour_are_not_units() -> None:
    assert _unit("BP 90/60 c/o dizzy", "60") is None
    assert _unit("BP 90/60 C/o dizzy", "60") is None
    assert _unit("2 Foley", "2") is None
    assert _unit("100 mL/hr", "100") is None
    assert _unit("3 cc2", "3") is None
    assert _unit("5\nF", "5") is None


def test_units_outside_the_table_are_none() -> None:
    for text, number in [
        ("BP 90/60 mmHg", "60"),
        ("HR 96 bpm", "96"),
        ("SpO2 95%", "95"),
        ("30 gtts/min", "30"),
        ("500 mg", "500"),
        ("2 L nasal", "2"),
        ("37.4 f", "37.4"),
        ("37.4", "37.4"),
    ]:
        assert _unit(text, number) is None, text


def _tokens(text: str) -> list[str]:
    return [token for token, _ in numbers_in(text)]


def test_leading_dot_decimal_is_one_number() -> None:
    assert numbers_in("lorazepam .5 mg") == [(".5", Span(start=10, end=12))]
    assert numbers_in("x.5") == [(".5", Span(start=1, end=3))]
    assert _tokens("37.5") == ["37.5"]
    assert number_value(".5") == number_value("0.5")


def test_numbers_joined_by_a_slash_are_one_group() -> None:
    assert _tokens("gave 1/2 tab, pain 2-3/10, BP 90/60/70") == ["1/2", "2", "3/10", "90/60/70"]
    assert number_value("90/60") != number_value("90")
    assert number_value("90/60") == number_value("90.0/060")


def test_vulgar_fraction_is_one_group_equal_to_its_slash_form() -> None:
    assert numbers_in("took ½ tab") == [("½", Span(start=5, end=6))]
    assert _tokens("¼ and ⅜ and ⅒") == ["¼", "⅜", "⅒"]
    assert number_value("½") == number_value("1/2")
    assert number_value("¾") == number_value("3/4")


def test_superscript_and_subscript_digits_are_not_numbers() -> None:
    assert _tokens("10³ and H₂O and 2²") == ["10", "2"]


def test_digits_with_letters_on_both_sides_are_part_of_a_word() -> None:
    assert _tokens("D5LR, D5W, q4h, a1c") == []
    assert _tokens("D5.5LR 7") == ["7"]


def test_digits_at_the_end_of_a_word_stay_numbers() -> None:
    assert _tokens("HR120 BT37.4 SpO2 x4 5HR") == ["120", "37.4", "2", "4", "5"]


def _unit_end(text: str, number: str) -> tuple[Ucum, int] | None:
    start = text.index(number)
    return unit_end_after(text, Span(start=start, end=start + len(number)))


def test_unit_spellings_are_folded_and_ends_stay_in_the_typed_text() -> None:
    assert _unit_end("T 37.4 \u2109 x", "37.4") == (Ucum.DEG_F, 8)
    assert _unit_end("T 37.4\u2103.", "37.4") == (Ucum.CEL, 7)
    assert _unit_end("T 37.4\u00a0\u00b0F", "37.4") == (Ucum.DEG_F, 9)
    assert _unit_end("T 37.4\u00baF", "37.4") == (Ucum.DEG_F, 8)
    assert _unit_end("T 37.4\u02daC", "37.4") == (Ucum.CEL, 8)
    assert _unit_end("T 37.4\u00b0 F", "37.4") == (Ucum.DEG_F, 9)
    assert _unit_end("T 37.4 \u00b0", "37.4") is None
    assert _unit_end("T 37.4 \u00b0 mL", "37.4") is None
    assert _unit_end("T 37.4 \u2109ahrenheit", "37.4") is None


def test_hash_must_not_be_followed_by_a_letter_digit_or_slash() -> None:
    assert _unit("wt 176#3", "176") is None
    assert _unit("wt 176#a", "176") is None
    assert _unit("wt 176#/", "176") is None
    assert _unit("wt 176#", "176") is Ucum.LB
    assert _unit("wt 176# today", "176") is Ucum.LB
