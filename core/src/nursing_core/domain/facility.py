"""The per-facility region profile.

The facility row is the truth: the presets below only fill a new row, and the admin edits it
afterwards. No code path asks which country a facility is in; it reads the profile. Every edit
passes the same rules as the presets.
"""

from datetime import date, datetime, time, timedelta
from enum import StrEnum
from functools import cache
from typing import Annotated, Literal, Self
from zoneinfo import ZoneInfo, available_timezones

from pydantic import (
    AfterValidator,
    Field,
    PositiveInt,
    StringConstraints,
    field_validator,
    model_validator,
)

from nursing_core.domain import DomainModel
from nursing_core.domain.units import Ucum, UnitDefaults

DAY = timedelta(days=1)
# Names whose meaning depends on the host's own files, which a Lambda image doesn't have.
_HOST_ZONES = frozenset({"localtime", "posixrules", "Factory"})


@cache
def _known_zones() -> frozenset[str]:
    return frozenset(available_timezones()) - _HOST_ZONES


class NoteFormat(StrEnum):
    """Only the formats built so far. A US DAR note is this format, labelled "DAR" in en-US."""

    FDAR = "fdar"


class Locale(StrEnum):
    EN_PH = "en-PH"
    EN_US = "en-US"


class ShiftInk(StrEnum):
    """Named by the ink paper charts use, never by role or clock label."""

    BLUE = "blue"
    BLACK = "black"
    RED = "red"


Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def _whole_minutes(value: time) -> time:
    if value.tzinfo is not None or value.second or value.microsecond:
        raise ValueError("a local clock time in whole minutes, without a timezone")
    return value


LocalTime = Annotated[time, AfterValidator(_whole_minutes)]


def _minutes(value: time) -> int:
    return value.hour * 60 + value.minute


class ShiftDefinition(DomainModel):
    code: Annotated[Text, StringConstraints(max_length=16)]
    label: Annotated[Text, StringConstraints(max_length=40)]
    starts_local: LocalTime
    ends_local: LocalTime
    ink: ShiftInk

    @model_validator(mode="after")
    def _has_a_length(self) -> Self:
        if self.starts_local == self.ends_local:
            raise ValueError("a shift must end at a different time than it starts")
        return self


class FacilitySettings(DomainModel):
    """Everything the admin edits. The key is not here: it never changes."""

    name: Annotated[Text, StringConstraints(max_length=120)]
    timezone: str
    locale: Locale
    day_starts_at: LocalTime
    shifts: list[ShiftDefinition] = Field(min_length=1)
    note_formats: list[NoteFormat] = Field(min_length=1)
    default_note_format: NoteFormat
    units: UnitDefaults
    clock: Literal["24h", "12h"] = "24h"

    @field_validator("timezone")
    @classmethod
    def _real_iana_zone(cls, value: str) -> str:
        if value not in _known_zones():
            raise ValueError("timezone must be an IANA zone such as Asia/Manila")
        return value

    @model_validator(mode="after")
    def _shifts_tile_the_day(self) -> Self:
        codes = [s.code for s in self.shifts]
        if len(set(codes)) != len(codes):
            raise ValueError("shift codes must be unique")
        ordered = sorted(self.shifts, key=lambda s: _minutes(s.starts_local))
        for current, following in zip(ordered, ordered[1:] + ordered[:1], strict=True):
            if current.ends_local != following.starts_local:
                raise ValueError("shifts must cover 24 hours with no gap or overlap")
        if self.day_starts_at not in {s.starts_local for s in self.shifts}:
            raise ValueError("day_starts_at must be the start of one of the shifts")
        if len(set(self.note_formats)) != len(self.note_formats):
            raise ValueError("note formats must be unique")
        if self.default_note_format not in self.note_formats:
            raise ValueError("the default note format must be one of the note formats")
        return self

    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def shift_date(self, local_start: datetime) -> date:
        """The nursing day a shift starting at this local wall-clock time belongs to.

        A day that starts in the morning (06:00) names the day it starts on; a day that starts
        at noon or later (22:00) is named after the next calendar day, as a ward that dates
        its night shift by the next morning does.
        """
        offset = timedelta(minutes=_minutes(self.day_starts_at))
        if self.day_starts_at < time(12):
            return (local_start - offset).date()
        return (local_start + (DAY - offset)).date()


class FacilityProfile(FacilitySettings):
    key: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,39}$")]


class StoredFacility(DomainModel):
    profile: FacilityProfile
    version: PositiveInt


def _shift(code: str, start: int, end: int, ink: ShiftInk) -> ShiftDefinition:
    return ShiftDefinition(
        code=code, label=code, starts_local=time(start), ends_local=time(end), ink=ink
    )


def preset(region: Literal["PH", "US"], key: str, name: str) -> FacilityProfile:
    """A template for a new facility row: the Philippine or the US defaults."""
    if region == "PH":
        return FacilityProfile(
            key=key,
            name=name,
            timezone="Asia/Manila",
            locale=Locale.EN_PH,
            day_starts_at=time(6),
            shifts=[
                _shift("6-2", 6, 14, ShiftInk.BLUE),
                _shift("2-10", 14, 22, ShiftInk.BLACK),
                _shift("10-6", 22, 6, ShiftInk.RED),
            ],
            note_formats=[NoteFormat.FDAR],
            default_note_format=NoteFormat.FDAR,
            units=UnitDefaults(temperature=Ucum.CEL, weight=Ucum.KG, volume=Ucum.ML),
        )
    return FacilityProfile(
        key=key,
        name=name,
        timezone="America/Los_Angeles",
        locale=Locale.EN_US,
        day_starts_at=time(7),
        shifts=[
            _shift("7a-7p", 7, 19, ShiftInk.BLUE),
            _shift("7p-7a", 19, 7, ShiftInk.BLACK),
        ],
        note_formats=[NoteFormat.FDAR],
        default_note_format=NoteFormat.FDAR,
        units=UnitDefaults(temperature=Ucum.DEG_F, weight=None, volume=Ucum.ML),
    )
