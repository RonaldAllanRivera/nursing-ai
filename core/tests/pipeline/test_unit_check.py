"""Finding numbers in a line and reading the unit written right after one."""

from nursing_core.domain.notes import Span
from nursing_core.domain.units import Ucum
from nursing_core.pipeline.unit_check import numbers_in, unit_after


def _unit(text: str, number: str) -> Ucum | None:
    start = text.index(number)
    return unit_after(text, Span(start=start, end=start + len(number)))


def test_hash_after_a_number_is_pounds_but_ivf_hash_3_is_not() -> None:
    assert _unit("wt 176# today", "176") is Ucum.LB
    assert _unit("wt 176 # today", "176") is None
    assert _unit("IVF #3 running", "3") is None


def test_numbers_in_finds_decimals_and_numbers_inside_words() -> None:
    assert numbers_in("D5LR x4, SpO2 95%, BP 90/60, T 37.9") == [
        ("5", Span(start=1, end=2)),
        ("4", Span(start=6, end=7)),
        ("2", Span(start=12, end=13)),
        ("95", Span(start=14, end=16)),
        ("90", Span(start=22, end=24)),
        ("60", Span(start=25, end=27)),
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
