"""The per-facility region profile: one set of rules for the presets and every admin edit."""

from datetime import time
from decimal import Decimal
from typing import Any

import pytest
from nursing_core.domain.facility import (
    FacilityProfile,
    FacilitySettings,
    Locale,
    NoteFormat,
    ShiftDefinition,
    ShiftInk,
    StoredFacility,
    preset,
)
from nursing_core.domain.units import Quantity, Ucum, UnitDefaults
from pydantic import ValidationError


def shift(code: str, start: int, end: int, ink: ShiftInk = ShiftInk.BLUE) -> dict[str, Any]:
    return {
        "code": code,
        "label": code,
        "starts_local": time(start),
        "ends_local": time(end),
        "ink": ink,
    }


def settings(**changes: Any) -> dict[str, Any]:
    """A valid PH-like settings body; each test changes one thing."""
    body: dict[str, Any] = {
        "name": "SYNTHETIC Demo Hospital",
        "timezone": "Asia/Manila",
        "locale": Locale.EN_PH,
        "day_starts_at": time(6),
        "shifts": [shift("6-2", 6, 14), shift("2-10", 14, 22), shift("10-6", 22, 6)],
        "note_formats": [NoteFormat.FDAR],
        "default_note_format": NoteFormat.FDAR,
        "units": {"temperature": Ucum.CEL, "weight": Ucum.KG, "volume": Ucum.ML},
    }
    body.update(changes)
    return body


def test_valid_settings_load() -> None:
    loaded = FacilitySettings.model_validate(settings())
    assert loaded.clock == "24h"
    assert [s.code for s in loaded.shifts] == ["6-2", "2-10", "10-6"]


def test_shifts_must_tile_the_day_without_a_gap() -> None:
    gap = [shift("6-2", 6, 14), shift("2-10", 14, 21), shift("10-6", 22, 6)]
    with pytest.raises(ValidationError, match="24 hours"):
        FacilitySettings.model_validate(settings(shifts=gap))


def test_shifts_must_tile_the_day_without_an_overlap() -> None:
    overlap = [shift("6-2", 6, 15), shift("2-10", 14, 22), shift("10-6", 22, 6)]
    with pytest.raises(ValidationError, match="24 hours"):
        FacilitySettings.model_validate(settings(shifts=overlap))


def test_shift_codes_must_be_unique() -> None:
    twice = [shift("day", 7, 19), shift("day", 19, 7)]
    with pytest.raises(ValidationError, match="unique"):
        FacilitySettings.model_validate(settings(shifts=twice, day_starts_at=time(7)))


def test_shift_must_not_start_and_end_at_the_same_time() -> None:
    with pytest.raises(ValidationError):
        ShiftDefinition.model_validate(shift("all", 7, 7))


def test_shift_times_are_whole_minutes() -> None:
    body = shift("6-2", 6, 14) | {"starts_local": time(6, 0, 30)}
    with pytest.raises(ValidationError):
        ShiftDefinition.model_validate(body)


def test_day_must_start_at_a_shift_start() -> None:
    with pytest.raises(ValidationError, match="day_starts_at"):
        FacilitySettings.model_validate(settings(day_starts_at=time(7)))


def test_timezone_must_be_a_real_iana_zone() -> None:
    for bad in ("Mars/Olympus_Mons", "../etc/passwd", "", "localtime", "posixrules", "A" * 300):
        with pytest.raises(ValidationError, match="timezone"):
            FacilitySettings.model_validate(settings(timezone=bad))


def test_default_format_must_be_one_of_the_formats() -> None:
    with pytest.raises(ValidationError):
        FacilitySettings.model_validate(settings(note_formats=[]))


def test_unit_defaults_accept_only_their_measure() -> None:
    with pytest.raises(ValidationError):
        UnitDefaults(temperature=Ucum.KG, weight=None, volume=Ucum.ML)
    with pytest.raises(ValidationError):
        UnitDefaults(temperature=Ucum.CEL, weight=Ucum.ML, volume=Ucum.ML)
    with pytest.raises(ValidationError):
        UnitDefaults(temperature=Ucum.CEL, weight=None, volume=Ucum.KG)


def test_settings_refuse_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        FacilitySettings.model_validate(settings(key="renamed"))


def test_profile_key_is_a_short_slug() -> None:
    profile = FacilityProfile.model_validate(settings(key="ph-demo"))
    assert profile.key == "ph-demo"
    with pytest.raises(ValidationError):
        FacilityProfile.model_validate(settings(key="PH Demo!"))


def test_models_are_frozen() -> None:
    loaded = FacilitySettings.model_validate(settings())
    with pytest.raises(ValidationError):
        loaded.name = "changed"  # type: ignore[misc]


def test_stored_facility_version_is_positive() -> None:
    profile = preset("PH", "ph-demo", "SYNTHETIC Demo Hospital (PH)")
    assert StoredFacility(profile=profile, version=1).version == 1
    with pytest.raises(ValidationError):
        StoredFacility(profile=profile, version=0)


def test_quantity_keeps_the_value_and_ucum_code() -> None:
    temp = Quantity(value=Decimal("37.9"), unit=Ucum.CEL)
    assert temp.model_dump(mode="json") == {"value": "37.9", "unit": "Cel"}


def test_ph_preset_matches_the_region_table() -> None:
    ph = preset("PH", "ph-demo", "SYNTHETIC Demo Hospital (PH)")
    assert ph.key == "ph-demo"
    assert ph.name == "SYNTHETIC Demo Hospital (PH)"
    assert ph.timezone == "Asia/Manila"
    assert ph.locale is Locale.EN_PH
    assert ph.day_starts_at == time(6)
    assert [(s.code, s.starts_local, s.ends_local, s.ink) for s in ph.shifts] == [
        ("6-2", time(6), time(14), ShiftInk.BLUE),
        ("2-10", time(14), time(22), ShiftInk.BLACK),
        ("10-6", time(22), time(6), ShiftInk.RED),
    ]
    assert ph.note_formats == [NoteFormat.FDAR]
    assert ph.default_note_format is NoteFormat.FDAR
    assert ph.units == UnitDefaults(temperature=Ucum.CEL, weight=Ucum.KG, volume=Ucum.ML)
    assert ph.clock == "24h"


def test_us_preset_matches_the_region_table() -> None:
    us = preset("US", "us-demo", "SYNTHETIC Demo Hospital (US)")
    assert us.timezone == "America/Los_Angeles"
    assert us.locale is Locale.EN_US
    assert us.day_starts_at == time(7)
    assert [(s.code, s.starts_local, s.ends_local, s.ink) for s in us.shifts] == [
        ("7a-7p", time(7), time(19), ShiftInk.BLUE),
        ("7p-7a", time(19), time(7), ShiftInk.BLACK),
    ]
    assert us.note_formats == [NoteFormat.FDAR]
    assert us.clock == "24h"


def test_us_preset_has_no_default_weight_unit() -> None:
    us = preset("US", "us-demo", "SYNTHETIC Demo Hospital (US)")
    assert us.units == UnitDefaults(temperature=Ucum.DEG_F, weight=None, volume=Ucum.ML)


def test_presets_session_max_hours_ph_12_us_14() -> None:
    # A US 12-hour shift plus handover and late charting runs past 12 hours.
    assert preset("PH", "ph-x", "PH").session_max_hours == 12
    assert preset("US", "us-x", "US").session_max_hours == 14


def test_settings_saved_before_p2_read_as_12_hours() -> None:
    # A P1 `facility_change` row's JSON has no `session_max_hours`.
    saved_in_p1 = preset("PH", "ph-x", "PH").model_dump(mode="json", exclude={"key"})
    del saved_in_p1["session_max_hours"]
    assert FacilitySettings.model_validate(saved_in_p1).session_max_hours == 12


def test_session_max_hours_is_between_1_and_24() -> None:
    saved = preset("PH", "ph-x", "PH").model_dump(mode="json", exclude={"key"})
    for hours in (1, 24):
        assert FacilitySettings.model_validate({**saved, "session_max_hours": hours})
    for hours in (0, 25):
        with pytest.raises(ValidationError):
            FacilitySettings.model_validate({**saved, "session_max_hours": hours})
