"""Clocks for the `Clock` port: the real one, and a fixed one for tests and demo exports."""

from datetime import UTC, datetime


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    def __init__(self, at: datetime) -> None:
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("naive datetime: pass a timezone-aware instant")
        self._at = at.astimezone(UTC)

    def now(self) -> datetime:
        return self._at
