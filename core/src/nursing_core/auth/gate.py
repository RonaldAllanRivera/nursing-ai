"""The session gate: the one place that decides what a signed-in session may do right now."""

from datetime import datetime, timedelta

from nursing_core.domain.users import SessionGate


def session_gate(
    *,
    has_pin: bool,
    pin_locked: bool,
    pin_verified_at: datetime | None,
    last_active_at: datetime,
    now: datetime,
    idle_lock: timedelta,
) -> SessionGate:
    """The gate of a session at `now`.

    The first that applies wins: a locked PIN, no PIN yet, a PIN not yet entered in this
    session, no activity for the idle-lock time (exactly at the limit counts as idle), else open.
    """
    if pin_locked:
        return SessionGate.PIN_LOCKED
    if not has_pin:
        return SessionGate.SET_PIN
    if pin_verified_at is None:
        return SessionGate.ENTER_PIN
    if now - last_active_at >= idle_lock:
        return SessionGate.IDLE_LOCKED
    return SessionGate.OPEN
