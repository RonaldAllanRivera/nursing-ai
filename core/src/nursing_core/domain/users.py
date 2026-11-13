"""Roles, and the permission rules enforced so far (route-by-route checks come later)."""

from enum import StrEnum


class Role(StrEnum):
    STAFF_NURSE = "staff_nurse"
    HEAD_NURSE = "head_nurse"
    ADMIN = "admin"


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
