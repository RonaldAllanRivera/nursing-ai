"""Small mappings between domain values and table columns, shared by every storage module."""

from typing import Any
from uuid import UUID

from sqlalchemy import Row

from nursing_core.domain.facility import FacilitySettings, ShiftDefinition
from nursing_core.domain.shifts import ShiftRef

AnyRow = Row[*tuple[Any, ...]]


def facility_columns(settings: FacilitySettings) -> dict[str, object]:
    """The facility columns the admin can edit (a profile works too: its key is left out)."""
    return {
        "name": settings.name,
        "timezone": settings.timezone,
        "locale": settings.locale.value,
        "day_starts_at": settings.day_starts_at,
        "note_formats": [f.value for f in settings.note_formats],
        "default_note_format": settings.default_note_format.value,
        "unit_temperature": settings.units.temperature.value,
        "unit_weight": settings.units.weight.value if settings.units.weight else None,
        "unit_volume": settings.units.volume.value,
        "clock": settings.clock,
    }


def shift_rows(facility_id: UUID, shifts: list[ShiftDefinition]) -> list[dict[str, object]]:
    """The `shift_definition` rows for a facility, in the order given."""
    return [
        {
            "facility_id": facility_id,
            "position": position,
            "code": shift.code,
            "label": shift.label,
            "starts_local": shift.starts_local,
            "ends_local": shift.ends_local,
            "ink": shift.ink.value,
        }
        for position, shift in enumerate(shifts)
    ]


def shift_columns(shift: ShiftRef | None) -> dict[str, object]:
    """A shift snapshot as columns; None (the admin's session) gives all-null columns."""
    return {
        "shift_code": shift.code if shift else None,
        "shift_label": shift.label if shift else None,
        "shift_starts_at": shift.starts_at if shift else None,
        "shift_ends_at": shift.ends_at if shift else None,
        "shift_date": shift.shift_date if shift else None,
        "shift_timezone": shift.timezone if shift else None,
    }


def shift_from_row(row: AnyRow) -> ShiftRef:
    """The shift snapshot held in a row's `shift_*` columns, which must all be set."""
    return ShiftRef(
        code=row.shift_code,
        label=row.shift_label,
        starts_at=row.shift_starts_at,
        ends_at=row.shift_ends_at,
        shift_date=row.shift_date,
        timezone=row.shift_timezone,
    )


def optional_shift_from_row(row: AnyRow) -> ShiftRef | None:
    """Like `shift_from_row`, but a row with no shift (the admin's session) gives None."""
    return shift_from_row(row) if row.shift_code is not None else None
