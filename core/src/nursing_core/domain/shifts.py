"""Which shift an instant falls in, from the facility's local clock times.

Shift edges are local wall-clock times in the facility's IANA zone, converted to UTC, so a US
night shift lasts 11 or 13 hours on the nights the clocks change. Shifts are half-open,
[start, end). The clock only suggests a shift: the nurse's session decides which one she is
working, and each note keeps a snapshot of it.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Self

from pydantic import AwareDatetime, field_validator, model_validator

from nursing_core.domain import DomainModel
from nursing_core.domain.facility import DAY, FacilitySettings

# Local dates either side of the instant: enough for the previous and next shift of any tiling.
_SPAN = range(-2, 3)


class ShiftRef(DomainModel):
    """A shift as worked: the snapshot a note keeps. Later profile edits never change it."""

    code: str
    label: str
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    shift_date: date
    timezone: str

    @field_validator("starts_at", "ends_at")
    @classmethod
    def _in_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _ends_after_it_starts(self) -> Self:
        if self.ends_at <= self.starts_at:
            raise ValueError("a shift must end after it starts")
        return self


def _require_aware(instant: datetime) -> datetime:
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("naive datetime: pass a timezone-aware instant")
    return instant


def _shifts_around(instant: datetime, facility: FacilitySettings) -> list[ShiftRef]:
    """Every shift that starts within two local days of the instant, in time order."""
    zone = facility.zone()
    today = _require_aware(instant).astimezone(zone).date()
    found: list[ShiftRef] = []
    for offset in _SPAN:
        day = today + timedelta(days=offset)
        for shift in facility.shifts:
            local_start = datetime.combine(day, shift.starts_local)
            end_day = day if shift.ends_local > shift.starts_local else day + DAY
            local_end = datetime.combine(end_day, shift.ends_local)
            found.append(
                ShiftRef(
                    code=shift.code,
                    label=shift.label,
                    starts_at=local_start.replace(tzinfo=zone),
                    ends_at=local_end.replace(tzinfo=zone),
                    shift_date=facility.shift_date(local_start),
                    timezone=facility.timezone,
                )
            )
    return sorted(found, key=lambda ref: ref.starts_at)


def _index_containing(instant: datetime, shifts: list[ShiftRef]) -> int:
    for index, ref in enumerate(shifts):
        if ref.starts_at <= instant < ref.ends_at:
            return index
    raise ValueError("no shift contains this instant")  # unreachable for a valid profile


def shift_containing(instant: datetime, facility: FacilitySettings) -> ShiftRef:
    shifts = _shifts_around(instant, facility)
    return shifts[_index_containing(instant, shifts)]


def default_shift(instant: datetime, facility: FacilitySettings) -> ShiftRef:
    """The shift whose start is nearest: a nurse signing in at 13:50 or 14:10 gets the 2-10."""
    shifts = _shifts_around(instant, facility)
    # Nearest start first; on a tie the later shift wins (shifts are in time order).
    _, nearest = min(
        enumerate(shifts), key=lambda pair: (abs(pair[1].starts_at - instant), -pair[0])
    )
    return nearest


def shift_choices(instant: datetime, facility: FacilitySettings) -> list[ShiftRef]:
    """The previous, containing and next shift: what a nurse may switch her session to."""
    shifts = _shifts_around(instant, facility)
    index = _index_containing(instant, shifts)
    return shifts[index - 1 : index + 2]
