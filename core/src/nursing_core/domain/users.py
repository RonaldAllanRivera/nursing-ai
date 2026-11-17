"""Roles, the permission rules, and the words a session's gate and a user's status use."""

from enum import StrEnum
from uuid import UUID


class Role(StrEnum):
    STAFF_NURSE = "staff_nurse"
    HEAD_NURSE = "head_nurse"
    ADMIN = "admin"


class SessionGate(StrEnum):
    """What a session may do now. The server decides it on every request: only `open` reaches
    patient data; the others name the screen the web app shows instead."""

    OPEN = "open"
    SET_PIN = "set_pin"  # signed in with Google for the first time: choose a PIN
    ENTER_PIN = "enter_pin"  # signed in: prove it is still her
    IDLE_LOCKED = "idle_locked"  # no activity for the idle-lock minutes
    PIN_LOCKED = "pin_locked"  # five wrong PINs: a head nurse or the admin resets it in person


class UserStatus(StrEnum):
    """An invited person reads `invited` until the first Google sign-in. Revoked rows stay,
    because signed notes point at their author."""

    INVITED = "invited"
    ACTIVE = "active"
    REVOKED = "revoked"


def can_edit_settings(role: Role) -> bool:
    """Only the admin edits a facility's settings."""
    return role is Role.ADMIN


def can_write_notes(role: Role) -> bool:
    """Only nurses write, edit, sign or discard notes: an admin doesn't chart."""
    return role in {Role.STAFF_NURSE, Role.HEAD_NURSE}


def can_see_facility(role: Role, own_facility_key: str | None, facility_key: str) -> bool:
    """The admin works across every facility; a nurse sees only her own."""
    if role is Role.ADMIN:
        return True
    return own_facility_key is not None and own_facility_key == facility_key


# A demo persona's PIN is printed on the demo's sign-in page, so anyone can be one. None of the
# staff rules below ever let a persona see, invite, revoke or unlock a real person.


def can_manage_staff(role: Role, *, persona: bool) -> bool:
    """Only the admin invites and revokes people, and never the demo's admin persona."""
    return role is Role.ADMIN and not persona


def can_list_staff(role: Role, *, persona: bool) -> bool:
    """The admin sees everyone; a head nurse sees her facility's staff. Personas see no one."""
    return role in {Role.ADMIN, Role.HEAD_NURSE} and not persona


def can_reset_pin(
    *,
    actor_role: Role,
    actor_facility: str | None,
    actor_id: UUID,
    actor_persona: bool,
    target_role: Role,
    target_facility: str | None,
    target_id: UUID,
    target_persona: bool,
) -> bool:
    """Who may reset whose locked PIN, in person.

    Nobody resets a persona (a visitor's wrong tries end only that visitor's session) or their
    own PIN, and a persona resets no one. The admin resets anyone else; a head nurse resets a
    nurse of her own facility.
    """
    if actor_persona or target_persona or target_id == actor_id:
        return False
    if actor_role is Role.ADMIN:
        return True
    return (
        actor_role is Role.HEAD_NURSE
        and target_role in {Role.STAFF_NURSE, Role.HEAD_NURSE}
        and actor_facility is not None
        and actor_facility == target_facility
    )
