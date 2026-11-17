"""Who may manage, list and unlock staff, and the words a session's gate and a user's status use."""

from uuid import UUID, uuid4

import pytest
from nursing_core.domain.users import (
    Role,
    SessionGate,
    UserStatus,
    can_list_staff,
    can_manage_staff,
    can_reset_pin,
)

PH = "ph-demo"
US = "us-demo"


def reset(
    actor_role: Role,
    actor_facility: str | None,
    target_role: Role,
    target_facility: str | None,
    *,
    herself: bool = False,
    target_persona: bool = False,
) -> bool:
    actor_id = uuid4()
    target_id: UUID = actor_id if herself else uuid4()
    return can_reset_pin(
        actor_role=actor_role,
        actor_facility=actor_facility,
        actor_id=actor_id,
        target_role=target_role,
        target_facility=target_facility,
        target_id=target_id,
        target_persona=target_persona,
    )


def test_gates_and_statuses_use_the_contracts_words() -> None:
    assert [g.value for g in SessionGate] == [
        "open",
        "set_pin",
        "enter_pin",
        "idle_locked",
        "pin_locked",
    ]
    assert [s.value for s in UserStatus] == ["invited", "active", "revoked"]


@pytest.mark.parametrize(
    ("role", "manages", "lists"),
    [
        (Role.ADMIN, True, True),
        (Role.HEAD_NURSE, False, True),
        (Role.STAFF_NURSE, False, False),
    ],
)
def test_only_the_admin_manages_staff_and_head_nurses_also_list_it(
    role: Role, manages: bool, lists: bool
) -> None:
    assert can_manage_staff(role) is manages
    assert can_list_staff(role) is lists


def test_head_nurse_resets_only_her_facilitys_nurses() -> None:
    assert reset(Role.HEAD_NURSE, PH, Role.STAFF_NURSE, PH) is True
    assert reset(Role.HEAD_NURSE, PH, Role.HEAD_NURSE, PH) is True
    assert reset(Role.HEAD_NURSE, PH, Role.STAFF_NURSE, US) is False
    assert reset(Role.HEAD_NURSE, PH, Role.HEAD_NURSE, PH, herself=True) is False
    assert reset(Role.HEAD_NURSE, PH, Role.ADMIN, None) is False
    assert reset(Role.HEAD_NURSE, None, Role.STAFF_NURSE, None) is False


def test_staff_nurse_resets_nobody() -> None:
    assert reset(Role.STAFF_NURSE, PH, Role.STAFF_NURSE, PH) is False
    assert reset(Role.STAFF_NURSE, PH, Role.STAFF_NURSE, PH, herself=True) is False


def test_admin_resets_anyone_but_themselves() -> None:
    assert reset(Role.ADMIN, None, Role.STAFF_NURSE, PH) is True
    assert reset(Role.ADMIN, None, Role.HEAD_NURSE, US) is True
    assert reset(Role.ADMIN, None, Role.ADMIN, None) is True
    assert reset(Role.ADMIN, None, Role.ADMIN, None, herself=True) is False


def test_nobody_resets_a_persona() -> None:
    # A persona's wrong PINs end only that visitor's session; its row is never locked.
    assert reset(Role.ADMIN, None, Role.STAFF_NURSE, PH, target_persona=True) is False
    assert reset(Role.HEAD_NURSE, PH, Role.STAFF_NURSE, PH, target_persona=True) is False
