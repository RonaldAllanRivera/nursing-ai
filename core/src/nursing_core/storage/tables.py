"""The database tables, one SQLAlchemy Core `Table` each, on one `MetaData`.

The migrations in `migrations/versions/` are the fixed record of this schema; a test checks
that they and these tables agree. Ids are made by the application, so no id column has a default.
Every instant is `timestamptz`. A status column has a check constraint listing the values of
the domain enum it holds, read from the enum here so the two can't drift.
"""

from collections.abc import Iterable
from enum import StrEnum
from typing import get_args

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    Table,
    Text,
    Time,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from nursing_core.domain.facility import FacilitySettings, Locale, NoteFormat, ShiftInk
from nursing_core.domain.jobs import JobFailure, JobStatus
from nursing_core.domain.notes import NoteStatus
from nursing_core.domain.units import TEMPERATURE_UNITS, VOLUME_UNITS, WEIGHT_UNITS
from nursing_core.domain.users import Role

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)

_HEX64 = "'^[0-9a-f]{64}$'"


def _listed(values: Iterable[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _values(column: str, enum: type[StrEnum]) -> CheckConstraint:
    """A check that the column holds one of the enum's values (a null passes: add NOT NULL)."""
    return CheckConstraint(
        f"{column} IN ({_listed(m.value for m in enum)})", name=f"{column}_values"
    )


def _one_of(column: str, values: Iterable[str], *, or_null: bool = False) -> CheckConstraint:
    """The same check for a set of allowed values (sorted, so the SQL doesn't change run to run)."""
    allowed = f"{column} IN ({_listed(sorted(values))})"
    return CheckConstraint(
        f"{column} IS NULL OR {allowed}" if or_null else allowed, name=f"{column}_values"
    )


def _all_or_none(status: str, columns: list[str]) -> str:
    """Every column is set when the note has this status, and every one is null when it hasn't."""
    set_ = " AND ".join(f"{c} IS NOT NULL" for c in columns)
    unset = " AND ".join(f"{c} IS NULL" for c in columns)
    return f"(status = '{status}' AND {set_}) OR (status <> '{status}' AND {unset})"


def _pk() -> Column[object]:
    return Column("id", Uuid, primary_key=True)


def _fk(name: str, target: str, *, nullable: bool = False) -> Column[object]:
    return Column(name, Uuid, ForeignKey(target), nullable=nullable)


def _instant(name: str, *, nullable: bool = False) -> Column[object]:
    return Column(name, DateTime(timezone=True), nullable=nullable)


facility = Table(
    "facility",
    metadata,
    _pk(),
    Column("key", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("timezone", Text, nullable=False),
    Column("locale", Text, nullable=False),
    Column("day_starts_at", Time, nullable=False),
    Column("note_formats", ARRAY(Text), nullable=False),
    Column("default_note_format", Text, nullable=False),
    Column("unit_temperature", Text, nullable=False),
    Column("unit_weight", Text, nullable=True),
    Column("unit_volume", Text, nullable=False),
    Column("clock", Text, nullable=False),
    Column("session_max_hours", Integer, nullable=False, server_default=text("12")),
    Column("version", Integer, nullable=False),
    # app_user also points back at facility: `use_alter` marks this key as the one added last.
    Column("updated_by", Uuid, ForeignKey("app_user.id", use_alter=True), nullable=True),
    _instant("updated_at"),
    UniqueConstraint("key"),
    _values("locale", Locale),
    _values("default_note_format", NoteFormat),
    _one_of("unit_temperature", TEMPERATURE_UNITS),
    _one_of("unit_weight", WEIGHT_UNITS, or_null=True),
    _one_of("unit_volume", VOLUME_UNITS),
    _one_of("clock", get_args(FacilitySettings.model_fields["clock"].annotation)),
    CheckConstraint(
        f"note_formats <@ ARRAY[{_listed(f.value for f in NoteFormat)}]::text[]",
        name="note_formats_values",
    ),
    CheckConstraint("version > 0", name="version_positive"),
    CheckConstraint("cardinality(note_formats) > 0", name="has_a_note_format"),
    CheckConstraint("default_note_format = ANY (note_formats)", name="default_is_offered"),
    CheckConstraint("session_max_hours BETWEEN 1 AND 24", name="session_max_hours_range"),
)

shift_definition = Table(
    "shift_definition",
    metadata,
    Column("facility_id", Uuid, ForeignKey("facility.id"), primary_key=True),
    Column("position", Integer, primary_key=True),
    Column("code", Text, nullable=False),
    Column("label", Text, nullable=False),
    Column("starts_local", Time, nullable=False),
    Column("ends_local", Time, nullable=False),
    Column("ink", Text, nullable=False),
    UniqueConstraint("facility_id", "code"),
    _values("ink", ShiftInk),
    CheckConstraint("position >= 0", name="position_not_negative"),
    CheckConstraint("starts_local <> ends_local", name="has_a_length"),
)

app_user = Table(
    "app_user",
    metadata,
    _pk(),
    Column("display_name", Text, nullable=False),
    Column("initials", Text, nullable=False),
    Column("role", Text, nullable=False),
    _fk("facility_id", "facility.id", nullable=True),
    # Who signs in with Google: the invited email (stored lowercase) and the Google subject bound
    # at the first sign-in. A demo persona needs neither.
    Column("email", Text, nullable=True),
    Column("google_sub", Text, nullable=True),
    Column("persona", Boolean, nullable=False, server_default=text("false")),
    _instant("revoked_at", nullable=True),
    _fk("invited_by", "app_user.id", nullable=True),
    # The signing PIN's Argon2id hash, never the PIN; five wrong tries set `pin_locked_at`.
    Column("pin_hash", Text, nullable=True),
    Column("pin_failures", Integer, nullable=False, server_default=text("0")),
    _instant("pin_locked_at", nullable=True),
    UniqueConstraint("email"),
    UniqueConstraint("google_sub"),
    _values("role", Role),
    CheckConstraint("(facility_id IS NULL) = (role = 'admin')", name="admin_alone_has_no_facility"),
    CheckConstraint("email = lower(email)", name="email_is_lowercase"),
    CheckConstraint("persona OR email IS NOT NULL", name="email_unless_persona"),
    CheckConstraint("pin_failures >= 0", name="pin_failures_not_negative"),
)

facility_change = Table(
    "facility_change",
    metadata,
    _pk(),
    _fk("facility_id", "facility.id"),
    Column("version", Integer, nullable=False),
    _fk("changed_by", "app_user.id", nullable=True),
    _instant("changed_at"),
    Column("settings", JSONB, nullable=False),
    # A demo reset back to the preset (at a persona's sign-in): a row nobody wrote.
    Column("reset", Boolean, nullable=False, server_default=text("false")),
    UniqueConstraint("facility_id", "version"),
    CheckConstraint("version > 0", name="version_positive"),
    CheckConstraint(
        "changed_by IS NOT NULL OR version = 1 OR reset", name="author_unless_first_or_reset"
    ),
)

ward = Table(
    "ward",
    metadata,
    _pk(),
    _fk("facility_id", "facility.id"),
    Column("name", Text, nullable=False),
    UniqueConstraint("facility_id", "name"),
)

bed = Table(
    "bed",
    metadata,
    _pk(),
    _fk("ward_id", "ward.id"),
    Column("label", Text, nullable=False),
    UniqueConstraint("ward_id", "label"),
)

patient = Table(
    "patient",
    metadata,
    _pk(),
    _fk("facility_id", "facility.id"),
    Column("display_name", Text, nullable=False),
    Column("sex", Text, nullable=False),
    Column("birth_date", Date, nullable=False),
    Column("given_name", Text, nullable=False),
    Column("middle_name", Text, nullable=True),
    Column("family_name", Text, nullable=False),
    Column("suffix", Text, nullable=True),
    Column("nicknames", ARRAY(Text), nullable=False, server_default=text("'{}'")),
    Column("record_number", Text, nullable=False),
    Column("address", Text, nullable=True),
    Column("postal_code", Text, nullable=True),
    Column("synthetic", Boolean, nullable=False, server_default=text("true")),
    UniqueConstraint("facility_id", "record_number"),
)

patient_relative = Table(
    "patient_relative",
    metadata,
    Column("patient_id", Uuid, ForeignKey("patient.id"), primary_key=True),
    Column("position", Integer, primary_key=True),
    Column("name", Text, nullable=False),
    Column("relation", Text, nullable=False),
    CheckConstraint("position >= 0", name="position_not_negative"),
)

encounter = Table(
    "encounter",
    metadata,
    _pk(),
    _fk("patient_id", "patient.id"),
    _fk("bed_id", "bed.id"),
    _instant("admitted_at"),
    _instant("discharged_at", nullable=True),
    CheckConstraint("discharged_at IS NULL OR discharged_at >= admitted_at", name="stay_in_order"),
)

patient_context = Table(
    "patient_context",
    metadata,
    Column("encounter_id", Uuid, ForeignKey("encounter.id"), primary_key=True),
    Column("context", JSONB, nullable=False),
    _instant("updated_at"),
)

session = Table(
    "session",
    metadata,
    Column("token_hash", Text, primary_key=True),
    _fk("user_id", "app_user.id"),
    Column("shift_code", Text, nullable=True),
    Column("shift_label", Text, nullable=True),
    _instant("shift_starts_at", nullable=True),
    _instant("shift_ends_at", nullable=True),
    Column("shift_date", Date, nullable=True),
    Column("shift_timezone", Text, nullable=True),
    _instant("created_at"),
    _instant("expires_at"),
    # Sent back in the session's answer and required in X-CSRF-Token on every unsafe request.
    Column("csrf_token", Text, nullable=False),
    _instant("pin_verified_at", nullable=True),
    _instant("last_active_at"),
    # Wrong PINs typed in this session: what counts for a shared demo persona.
    Column("pin_failures", Integer, nullable=False, server_default=text("0")),
    CheckConstraint(
        "(shift_code IS NULL) = (shift_label IS NULL) "
        "AND (shift_code IS NULL) = (shift_starts_at IS NULL) "
        "AND (shift_code IS NULL) = (shift_ends_at IS NULL) "
        "AND (shift_code IS NULL) = (shift_date IS NULL) "
        "AND (shift_code IS NULL) = (shift_timezone IS NULL)",
        name="shift_all_or_none",
    ),
    CheckConstraint("expires_at > created_at", name="expires_after_creation"),
    CheckConstraint("pin_failures >= 0", name="pin_failures_not_negative"),
    Index("ix_session_user_id", "user_id"),
)

rough_note = Table(
    "rough_note",
    metadata,
    _pk(),
    _fk("encounter_id", "encounter.id"),
    _fk("author_id", "app_user.id"),
    Column("text", Text, nullable=False),
    _instant("written_at"),
    Column("note_format", Text, nullable=False),
    Column("shift_code", Text, nullable=False),
    Column("shift_label", Text, nullable=False),
    _instant("shift_starts_at"),
    _instant("shift_ends_at"),
    Column("shift_date", Date, nullable=False),
    Column("shift_timezone", Text, nullable=False),
    Column("idempotency_key", Text, nullable=False),
    Column("body_hash", Text, nullable=False),
    UniqueConstraint("author_id", "idempotency_key"),
    _values("note_format", NoteFormat),
    CheckConstraint(f"body_hash ~ {_HEX64}", name="body_hash_is_hex"),
    CheckConstraint("shift_ends_at > shift_starts_at", name="shift_has_a_length"),
    Index("ix_rough_note_encounter_id_shift_starts_at", "encounter_id", "shift_starts_at"),
)

note = Table(
    "note",
    metadata,
    _pk(),
    _fk("rough_note_id", "rough_note.id"),
    _fk("encounter_id", "encounter.id"),
    Column("status", Text, nullable=False),
    Column("version", Integer, nullable=False),
    Column("draft", JSONB, nullable=False),
    Column("checklist", JSONB, nullable=False),
    Column("generation", JSONB, nullable=False),
    _fk("signed_by", "app_user.id", nullable=True),
    _instant("signed_at", nullable=True),
    Column("content_hash", Text, nullable=True),
    _fk("discarded_by", "app_user.id", nullable=True),
    _instant("discarded_at", nullable=True),
    _instant("created_at"),
    _instant("updated_at"),
    UniqueConstraint("rough_note_id"),
    _values("status", NoteStatus),
    CheckConstraint("version > 0", name="version_positive"),
    CheckConstraint(f"content_hash ~ {_HEX64}", name="content_hash_is_hex"),
    CheckConstraint(
        _all_or_none("signed", ["signed_by", "signed_at", "content_hash"]),
        name="signature_only_when_signed",
    ),
    CheckConstraint(
        _all_or_none("discarded", ["discarded_by", "discarded_at"]),
        name="discard_only_when_discarded",
    ),
)

draft_job = Table(
    "draft_job",
    metadata,
    _pk(),
    _fk("rough_note_id", "rough_note.id"),
    Column("status", Text, nullable=False),
    Column("failure", Text, nullable=True),
    _fk("note_id", "note.id", nullable=True),
    _instant("created_at"),
    _instant("updated_at"),
    # A claim is a lease (SQS delivers at least once): each claim adds an attempt.
    Column("attempts", Integer, nullable=False, server_default=text("0")),
    _instant("claimed_at", nullable=True),
    _values("status", JobStatus),
    _values("failure", JobFailure),
    CheckConstraint("(status = 'failed') = (failure IS NOT NULL)", name="failure_only_when_failed"),
    CheckConstraint(
        "(status = 'succeeded') = (note_id IS NOT NULL)", name="note_only_when_succeeded"
    ),
    CheckConstraint("attempts >= 0", name="attempts_not_negative"),
    Index("ix_draft_job_status", "status"),
    # A rough note may be drafted again after a failure, but never has two live jobs.
    Index(
        "uq_draft_job_rough_note_id_unless_failed",
        "rough_note_id",
        unique=True,
        postgresql_where=text(
            f"status IN ({_listed(s.value for s in JobStatus if s is not JobStatus.FAILED)})"
        ),
    ),
)

note_version = Table(
    "note_version",
    metadata,
    _pk(),
    _fk("note_id", "note.id"),
    Column("version", Integer, nullable=False),
    Column("content", JSONB, nullable=False),
    Column("content_hash", Text, nullable=False),
    _fk("signed_by", "app_user.id"),
    _instant("signed_at"),
    UniqueConstraint("note_id"),
    CheckConstraint("version > 0", name="version_positive"),
    CheckConstraint(f"content_hash ~ {_HEX64}", name="content_hash_is_hex"),
)

ai_usage = Table(
    "ai_usage",
    metadata,
    _pk(),
    _fk("job_id", "draft_job.id", nullable=True),
    Column("provider", Text, nullable=False),
    Column("model", Text, nullable=False),
    Column("prompt_version", Text, nullable=False),
    Column("input_tokens", Integer, nullable=False),
    Column("output_tokens", Integer, nullable=False),
    Column("cost_usd", Numeric(12, 6), nullable=False),
    _instant("created_at"),
    CheckConstraint("provider IN ('fake', 'replay', 'anthropic')", name="provider_values"),
    CheckConstraint("input_tokens >= 0 AND output_tokens >= 0", name="tokens_not_negative"),
    CheckConstraint("cost_usd >= 0", name="cost_not_negative"),
    Index("ix_ai_usage_created_at", "created_at"),
)

# The worst case of a live AI call in flight, counted against the monthly cap until its usage
# is recorded (the same transaction deletes it) or it expires after a crash.
ai_spend_hold = Table(
    "ai_spend_hold",
    metadata,
    _pk(),
    _fk("job_id", "draft_job.id", nullable=True),
    Column("amount_usd", Numeric(12, 6), nullable=False),
    _instant("created_at"),
    _instant("expires_at"),
    CheckConstraint("amount_usd > 0", name="amount_positive"),
    Index("ix_ai_spend_hold_expires_at", "expires_at"),
)
