"""Finding numbers in a line and reading the unit written right after one."""

from hypothesis import given
from hypothesis import strategies as st
from nursing_core.domain.notes import Span
from nursing_core.domain.units import Ucum
from nursing_core.pipeline.unit_check import (
    WrittenUnit,
    number_value,
    numbers_in,
    unit_after,
    unit_end_after,
    written_unit,
)


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


def test_c_slash_o_is_shorthand_and_not_a_unit() -> None:
    assert _unit("BP 90/60 c/o dizzy", "60") is None
    assert _unit("BP 90/60 C/o dizzy", "60") is None
    assert _unit("2 Foley", "2") is None
    assert _unit("T 38 c/o chills", "38") is None
    assert _unit("2 f/u", "2") is None
    assert _unit("5 u/a", "5") is None
    assert _unit("1 c/w", "1") is None
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
    assert _tokens("D5LR, D5W, q4h") == []
    assert _tokens("D5.5LR 7") == ["5.5", "7"]


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


def test_digits_between_a_label_and_a_unit_are_a_number() -> None:
    assert _tokens("BT37.9C HR121bpm BP120/80mmHg Wt80lb RR20cpm B12mg") == [
        "37.9",
        "121",
        "120/80",
        "80",
        "20",
        "12",
    ]
    assert _tokens("SpO2 HR120 x4 W80KG") == ["2", "120", "4", "80"]


def test_whole_digits_with_letters_that_are_not_a_unit_are_a_word() -> None:
    assert _tokens("D5LR D5W q4h D5NS") == []


def test_a_whole_number_with_a_fraction_is_one_mixed_number() -> None:
    assert numbers_in("gave 1½ tab") == [("1½", Span(start=5, end=7))]
    assert numbers_in("gave 1 1/2 tab") == [("1 1/2", Span(start=5, end=10))]
    assert _tokens("2 3/2 x, 1-1/2") == ["2", "3/2", "1", "1/2"]
    assert _tokens("gave 1  1/2") == ["1  1/2"]


def test_a_mixed_number_equals_its_other_spelling_but_nothing_else() -> None:
    assert number_value("1½") == number_value("1 1/2")
    assert number_value("1½") != number_value("1.5")
    assert number_value("1½") != number_value("1/2")
    assert number_value("1½") != number_value("1")
    assert number_value("1 1/2") != number_value("2 1/2")


def test_the_fraction_slash_and_the_full_width_slash_join_a_group() -> None:
    assert _tokens("1\u20442 and 1\uff0f2 and 90\uff0f60") == ["1\u20442", "1\uff0f2", "90\uff0f60"]
    assert number_value("1\u20442") == number_value("1/2") == number_value("1\uff0f2")
    assert number_value("1\u20442") == number_value("\u00bd")


def test_superscript_zero_is_read_as_a_degree_sign() -> None:
    assert _unit_end("T 37.4\u2070F", "37.4") == (Ucum.DEG_F, 8)
    assert _unit_end("T 37.4\u2070 C", "37.4") == (Ucum.CEL, 9)


def test_a_spaced_or_worded_fraction_after_a_whole_number_is_a_mixed_number() -> None:
    for written in ("1 \u00bd", "1\u00a0\u00bd", "1 and 1/2", "1 and \u00bd"):
        text = f"gave {written} tab"
        assert numbers_in(text) == [(written, Span(start=5, end=5 + len(written)))], written
        assert number_value(written) == number_value("1\u00bd"), written
    assert number_value("1 and 1/2") != number_value("1 and 2/3")
    assert _tokens("1 and 3/2") == ["1", "3/2"]


def test_a_degree_lookalike_is_not_a_letter_after_digits() -> None:
    assert _tokens("T38\u00baC. T38\u02daC T38\u2070C") == ["38", "38", "38"]
    assert _tokens("Wt81kgs") == ["81"]


def test_a_number_with_thousands_separators_is_one_number() -> None:
    assert numbers_in("heparin 5,000 units") == [("5,000", Span(start=8, end=13))]
    assert _tokens("WBC 12,500 and 5,000,000 and 1,000.5") == ["12,500", "5,000,000", "1,000.5"]
    assert number_value("5,000") == number_value("5000")
    assert number_value("5,000,000") == number_value("5000000")
    assert number_value("1,000.5") == number_value("1000.5")
    assert number_value("12,500") != number_value("12")


def test_a_comma_that_is_not_a_thousands_separator_splits_numbers() -> None:
    assert _tokens("5,0001 and 37,5 and 12,34") == ["5", "0001", "37", "5", "12", "34"]


def test_more_spacings_and_an_ampersand_join_a_mixed_number() -> None:
    for written in ("1 AND 1/2", "1 & 1/2", "1  \u00bd", "1\t\u00bd", "1 and\u00a01/2", "1  1/2"):
        text = f"GAVE {written} TAB"
        assert numbers_in(text) == [(written, Span(start=5, end=5 + len(written)))], written
        assert number_value(written) == number_value("1\u00bd"), written


def test_more_spellings_of_weight_and_temperature_units_are_read() -> None:
    cases = {
        "wt 80 kgs": Ucum.KG,
        "wt 80 kilogram": Ucum.KG,
        "wt 80 Kilograms": Ucum.KG,
        "wt 80 pound": Ucum.LB,
        "wt 80 POUNDS": Ucum.LB,
        "wt 80 Fahrenheit": Ucum.DEG_F,
        "wt 80 deg F": Ucum.DEG_F,
        "wt 80 degF": Ucum.DEG_F,
        "wt 80 degrees F": Ucum.DEG_F,
        "wt 80 degrees Fahrenheit": Ucum.DEG_F,
        "wt 80 Celsius": Ucum.CEL,
        "wt 80 deg C": Ucum.CEL,
        "wt 80 degrees c": Ucum.CEL,
        "wt 80 DEGREES CELSIUS": Ucum.CEL,
    }
    for text, unit in cases.items():
        assert _unit(text, "80") is unit, text
    for text in ("wt 80 pounded", "wt 80 deg Fx", "wt 80 degrees", "wt 80 f", "wt 80 kgsx"):
        assert _unit(text, "80") is None, text


@given(st.text())
def test_numbers_and_their_values_never_raise_on_arbitrary_text(text: str) -> None:
    for token, span in numbers_in(text):
        assert text[span.start : span.end] == token
        number_value(token)
        unit_end_after(text, span)


def _written(text: str, number: str) -> WrittenUnit | None:
    start = text.index(number)
    return written_unit(text, Span(start=start, end=start + len(number)))


def test_a_unit_followed_by_a_slash_and_letters_is_a_rate() -> None:
    assert _unit("100 mL/hr", "100") is Ucum.ML
    rate = _written("heparin 1000 units/hr.", "1000")
    assert rate is not None
    assert (rate.compared, rate.rate, rate.end) == ("units", ("hour",), 21)
    per_kg = _written("dopamine 5 mcg/kg/min", "5")
    assert per_kg is not None
    assert (per_kg.compared, per_kg.rate, per_kg.end) == ("mcg", ("kg", "minute"), 21)


def test_rate_denominators_are_read_by_meaning() -> None:
    for text, number, rate in [
        ("100 mL/h", "100", ("hour",)),
        ("100 mL/hrs", "100", ("hour",)),
        ("100 mL/Hour", "100", ("hour",)),
        ("5 mcg/mins", "5", ("minute",)),
        ("1 g/d", "1", ("day",)),
        ("1 L/h", "1", ("hour",)),
        ("1000 u/h", "1000", ("hour",)),
        ("5 mg/kgs/day", "5", ("kg", "day")),
        ("5 mg/cc", "5", ("ml",)),
        ("5 mg/dL", "5", ()),
        ("5 mg/kilogram/min", "5", ("kg", "minute")),
        ("5 mg/liter", "5", ("l",)),
        ("2 lpm", "2", ("minute",)),
        ("500 mg/tab", "500", ()),
        ("1000 units", "1000", ()),
    ]:
        written = _written(text, number)
        assert written is not None, text
        assert written.rate == rate, text


def test_a_slash_then_a_digit_ends_the_unit() -> None:
    written = _written("D5LR 1L/8hrs", "1")
    assert written is not None
    assert (written.compared, written.rate, written.end) == ("l", (), 7)
    assert [token for token, _ in numbers_in("D5LR 1L/8hrs")] == ["1", "8"]
    spaced = _written("1 L / 8 hrs", "1")
    assert spaced is not None
    assert spaced.rate == ()


def test_one_letter_shorthand_has_no_unit_at_all() -> None:
    for text, number in [("T 38 c/o chills", "38"), ("2 f/u", "2"), ("5 u/a", "5"), ("1 c/w", "1")]:
        assert _written(text, number) is None, text
    assert _written("1 U/A.", "1") is None
    assert _written("38 c/d", "38") is None
    assert _written("2 l/a", "2") is None
    assert _written("1 g/a", "1") is None
    assert _written("1 f/h", "1") is None


def test_spaces_around_a_slash_and_per_make_a_rate_only_for_known_denominators() -> None:
    for text, number, rate in [
        ("5 mcg / kg / min", "5", ("kg", "minute")),
        ("5 mcg/ kg/ min", "5", ("kg", "minute")),
        ("1000 units /hr", "1000", ("hour",)),
        ("1000 units per hour", "1000", ("hour",)),
        ("5 mcg PER kg per min", "5", ("kg", "minute")),
        ("2 L/m", "2", ("minute",)),
        ("5 mg per NGT", "5", ()),
        ("1 L / 8 hrs", "1", ()),
        ("1L/D5LR", "1", ()),
        ("5 mg/dose", "5", ()),
    ]:
        written = _written(text, number)
        assert written is not None, text
        assert written.rate == rate, text


def test_only_dose_and_volume_units_take_a_rate_in_the_reader() -> None:
    for text, number in [
        ("T 37.8C/HR 110", "37.8"),
        ("BP 120/80 mmHg/HR 80", "80"),
        ("80 kg/m", "80"),
    ]:
        written = _written(text, number)
        assert written is not None, text
        assert written.rate == (), text


def test_week_month_and_shift_are_denominators_and_long_rates_are_read_whole() -> None:
    for text, number, rate in [
        ("15 mg/week", "15", ("week",)),
        ("15 mg / wk", "15", ("week",)),
        ("15 mg per weeks", "15", ("week",)),
        ("15 mg/month", "15", ("month",)),
        ("15 mg/mo", "15", ("month",)),
        ("15 mg per months", "15", ("month",)),
        ("15 mg/shift", "15", ("shift",)),
        ("5 mcg per kilograms per minute", "5", ("kg", "minute")),
        ("5 micrograms per kilograms per minutes", "5", ("kg", "minute")),
        ("5 mcg per    kilograms   per        minute", "5", ("kg", "minute")),
    ]:
        written = _written(text, number)
        assert written is not None, text
        assert written.rate == rate, text
    whole = _written("5 mcg per kilograms per minute", "5")
    assert whole is not None
    assert whole.end == len("5 mcg per kilograms per minute")


def test_a_denominator_cut_by_the_end_of_the_read_is_finished_not_lost() -> None:
    head = "5 mcg/kg/"
    text = head + " " * (62 - len(head)) + "minute"
    written = _written(text, "5")
    assert written is not None
    assert written.rate == ("kg", "minute")


def test_the_read_after_a_number_stays_short_on_a_long_unpunctuated_note() -> None:
    from nursing_core.pipeline.unit_check import _fold_after  # pyright: ignore[reportPrivateUsage]

    text = "HR 88 " + "word " * 800
    folded, origin = _fold_after(text, 5)
    assert len(folded) == len(origin) <= 64 + len("word")
    assert written_unit("5 micrograms" + " " * 70 + "/kg/min", Span(start=0, end=1)) is not None
    far = _written("5 micrograms" + " " * 70 + "/kg/min", "5")
    assert far is not None
    assert far.rate == ()
