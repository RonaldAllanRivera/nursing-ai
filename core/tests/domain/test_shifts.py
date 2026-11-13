"""Shift maths: local clock times in the facility's zone, half-open, dated by the nursing day."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from nursing_core.clock import FixedClock, SystemClock
from nursing_core.domain.facility import FacilityProfile, preset
from nursing_core.domain.shifts import ShiftRef, default_shift, shift_choices, shift_containing
from pydantic import ValidationError

PH = preset("PH", "ph-demo", "SYNTHETIC Demo Hospital (PH)")
US = preset("US", "us-demo", "SYNTHETIC Demo Hospital (US)")
MANILA = ZoneInfo("Asia/Manila")
LA = ZoneInfo("America/Los_Angeles")


def at(zone: ZoneInfo, *parts: int) -> datetime:
    return datetime(*parts, tzinfo=zone)  # type: ignore[misc]


def test_shift_containing_after_midnight_is_the_shift_started_the_evening_before() -> None:
    found = shift_containing(at(MANILA, 2026, 11, 12, 1, 30), PH)
    assert found.code == "10-6"
    assert found.starts_at == at(MANILA, 2026, 11, 11, 22)
    assert found.ends_at == at(MANILA, 2026, 11, 12, 6)
    assert found.shift_date == date(2026, 11, 11)
    assert found.timezone == "Asia/Manila"


def test_shift_boundary_belongs_to_the_new_shift() -> None:
    found = shift_containing(at(MANILA, 2026, 11, 12, 14), PH)
    assert found.code == "2-10"
    assert found.starts_at == at(MANILA, 2026, 11, 12, 14)


def test_shift_ref_instants_are_utc() -> None:
    found = shift_containing(at(MANILA, 2026, 11, 12, 9), PH)
    assert found.starts_at.utcoffset() == timedelta(0)
    assert found.starts_at == datetime(2026, 11, 11, 22, tzinfo=UTC)


def test_dst_end_night_is_13_hours() -> None:
    found = shift_containing(at(LA, 2026, 11, 1, 3), US)
    assert found.code == "7p-7a"
    assert found.starts_at == at(LA, 2026, 10, 31, 19)
    assert found.ends_at == at(LA, 2026, 11, 1, 7)
    assert found.ends_at - found.starts_at == timedelta(hours=13)
    assert found.shift_date == date(2026, 10, 31)


def test_dst_start_night_is_11_hours() -> None:
    found = shift_containing(at(LA, 2026, 3, 7, 23), US)
    assert found.code == "7p-7a"
    assert found.ends_at - found.starts_at == timedelta(hours=11)


def test_default_shift_is_the_nearest_start() -> None:
    assert default_shift(at(MANILA, 2026, 11, 12, 14, 10), PH).code == "2-10"
    assert default_shift(at(MANILA, 2026, 11, 12, 13, 50), PH).code == "2-10"
    morning = default_shift(at(LA, 2026, 11, 12, 6, 50), US)
    assert morning.code == "7a-7p"
    assert morning.shift_date == date(2026, 11, 12)


def test_default_shift_tie_goes_to_the_later_shift() -> None:
    # 18:00 is 4 hours after the 2-10 start and 4 hours before the 10-6 start.
    assert default_shift(at(MANILA, 2026, 11, 12, 18), PH).code == "10-6"


def test_shift_choices_are_previous_containing_next() -> None:
    choices = shift_choices(at(MANILA, 2026, 11, 12, 14, 10), PH)
    assert [c.code for c in choices] == ["6-2", "2-10", "10-6"]
    assert [c.starts_at for c in choices] == [
        at(MANILA, 2026, 11, 12, 6),
        at(MANILA, 2026, 11, 12, 14),
        at(MANILA, 2026, 11, 12, 22),
    ]


def test_consecutive_shifts_share_their_edges() -> None:
    previous, current, following = shift_choices(at(LA, 2026, 11, 1, 3), US)
    assert previous.ends_at == current.starts_at
    assert current.ends_at == following.starts_at


def test_day_starting_at_2200_dates_the_night_shift_by_the_next_day() -> None:
    nights_next_day = FacilityProfile.model_validate(
        PH.model_dump() | {"key": "ph-next-day", "day_starts_at": time(22)}
    )
    night = shift_containing(at(MANILA, 2026, 11, 12, 23), nights_next_day)
    assert night.code == "10-6"
    assert night.shift_date == date(2026, 11, 13)
    afternoon = shift_containing(at(MANILA, 2026, 11, 13, 15), nights_next_day)
    assert afternoon.shift_date == date(2026, 11, 13)


@pytest.mark.parametrize("function", [shift_containing, default_shift, shift_choices])
def test_naive_datetime_is_refused(function: object) -> None:
    with pytest.raises(ValueError, match="naive"):
        function(datetime(2026, 11, 12, 9), PH)  # type: ignore[operator]


def test_shift_ref_must_end_after_it_starts() -> None:
    start = datetime(2026, 11, 12, tzinfo=UTC)
    with pytest.raises(ValidationError):
        ShiftRef(
            code="x",
            label="x",
            starts_at=start,
            ends_at=start,
            shift_date=date(2026, 11, 12),
            timezone="UTC",
        )


def test_fixed_clock_is_aware_utc() -> None:
    clock = FixedClock(at(MANILA, 2026, 11, 12, 5, 10))
    assert clock.now() == datetime(2026, 11, 11, 21, 10, tzinfo=UTC)
    assert clock.now().utcoffset() == timedelta(0)


def test_fixed_clock_refuses_naive_time() -> None:
    with pytest.raises(ValueError, match="naive"):
        FixedClock(datetime(2026, 11, 12, 5, 10))


def test_system_clock_is_aware_utc() -> None:
    assert SystemClock().now().utcoffset() == timedelta(0)
