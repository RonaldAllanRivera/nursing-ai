"""The session token is a secret: it must not show in a repr, a traceback or a log."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from nursing_api.budget import BudgetGuard
from nursing_api.deps import Nurse, SignedIn
from nursing_api.providers import provider_factory
from nursing_api.settings import Settings
from nursing_core.clock import FixedClock
from nursing_core.domain.shifts import ShiftRef
from nursing_core.domain.users import Role
from nursing_core.providers.fake import FakeProvider
from nursing_core.storage.accounts import StoredSession, StoredUser
from nursing_core.storage.repositories import PgUsageRepository
from pydantic import SecretStr

TOKEN = "zebracanary-session-token"  # noqa: S105 (a canary, not a password)
NOW = datetime(2026, 11, 12, 6, 0, tzinfo=UTC)


def a_user() -> StoredUser:
    return StoredUser(
        id=uuid4(),
        display_name="Demo Nurse",
        initials="DN",
        role=Role.STAFF_NURSE,
        facility_key="ph-demo",
    )


def a_shift() -> ShiftRef:
    return ShiftRef(
        code="day",
        label="Day",
        starts_at=NOW,
        ends_at=datetime(2026, 11, 12, 14, 0, tzinfo=UTC),
        shift_date=NOW.date(),
        timezone="UTC",
    )


def test_the_token_is_not_in_a_signed_in_repr() -> None:
    user = a_user()
    session = StoredSession(user_id=user.id, shift=a_shift(), expires_at=NOW)
    assert TOKEN not in repr(SignedIn(user=user, session=session, token=TOKEN))


def test_the_token_is_not_in_a_nurse_repr() -> None:
    nurse = Nurse(user=a_user(), facility_key="ph-demo", shift=a_shift(), token=TOKEN)
    assert TOKEN not in repr(nurse)


def test_live_mode_without_a_cap_is_refused_by_the_factory_itself() -> None:
    settings = Settings.model_validate(
        {
            "database_url": "postgresql+asyncpg://unused@localhost/unused",
            "ai_mode": "live",
            "anthropic_api_key": SecretStr("sk-zz9"),
        }
    )
    with pytest.raises(ValueError, match="live"):
        provider_factory(settings, PgUsageRepository.__new__(PgUsageRepository), FixedClock(NOW))


def test_live_mode_always_gets_the_budget_guard() -> None:
    settings = Settings.model_validate(
        {
            "database_url": "postgresql+asyncpg://unused@localhost/unused",
            "ai_mode": "live",
            "anthropic_api_key": SecretStr("sk-zz9"),
            "ai_monthly_cap_usd": Decimal("1.00"),
        }
    )
    usage = PgUsageRepository.__new__(PgUsageRepository)
    for_patient = provider_factory(
        settings, usage, FixedClock(NOW), lambda _patient: FakeProvider.__new__(FakeProvider)
    )
    assert isinstance(for_patient(object()), BudgetGuard)  # pyright: ignore[reportArgumentType]
