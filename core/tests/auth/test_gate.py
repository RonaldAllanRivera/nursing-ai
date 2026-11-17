"""The session gate's order: locked PIN, no PIN, PIN not entered, idle, open."""

from datetime import UTC, datetime, timedelta

import pytest
from nursing_core.auth.gate import session_gate
from nursing_core.domain.users import SessionGate

NOW = datetime(2026, 11, 12, 6, 0, tzinfo=UTC)
IDLE = timedelta(minutes=5)
HOUR = timedelta(hours=1)


def gate(
    *,
    has_pin: bool = True,
    pin_locked: bool = False,
    verified: bool = True,
    quiet_for: timedelta = timedelta(0),
) -> SessionGate:
    return session_gate(
        has_pin=has_pin,
        pin_locked=pin_locked,
        pin_verified_at=NOW - quiet_for if verified else None,
        last_active_at=NOW - quiet_for,
        now=NOW,
        idle_lock=IDLE,
    )


@pytest.mark.parametrize(
    ("has_pin", "pin_locked", "verified", "quiet_for", "expected"),
    [
        (True, False, True, timedelta(0), SessionGate.OPEN),
        (True, True, True, timedelta(0), SessionGate.PIN_LOCKED),
        (False, True, False, timedelta(0), SessionGate.PIN_LOCKED),
        (True, True, True, HOUR, SessionGate.PIN_LOCKED),
        (False, False, True, timedelta(0), SessionGate.SET_PIN),
        (False, False, False, timedelta(0), SessionGate.SET_PIN),
        (False, False, True, HOUR, SessionGate.SET_PIN),
        (True, False, False, timedelta(0), SessionGate.ENTER_PIN),
        (True, False, False, HOUR, SessionGate.ENTER_PIN),
        (True, False, True, HOUR, SessionGate.IDLE_LOCKED),
    ],
)
def test_gate_order(
    has_pin: bool, pin_locked: bool, verified: bool, quiet_for: timedelta, expected: SessionGate
) -> None:
    assert (
        gate(has_pin=has_pin, pin_locked=pin_locked, verified=verified, quiet_for=quiet_for)
        is expected
    )


def test_idle_exactly_at_the_limit_locks() -> None:
    assert gate(quiet_for=IDLE - timedelta(microseconds=1)) is SessionGate.OPEN
    assert gate(quiet_for=IDLE) is SessionGate.IDLE_LOCKED
