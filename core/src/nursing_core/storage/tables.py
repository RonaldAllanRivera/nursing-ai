"""The database tables, one SQLAlchemy Core `Table` each, on one `MetaData`.

The first migration (`migrations/versions/0001_initial.py`) is the fixed record of this schema;
a test checks the two agree. Ids are made by the application, so no id column has a default.
Every instant is `timestamptz`. A status column has a check constraint listing the values of
the domain enum it holds, read from the enum here so the two can't drift.
"""

from enum import StrEnum

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
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

from nursing_core.domain.facility import Locale, NoteFormat, ShiftInk
from nursing_core.domain.jobs import JobFailure, JobStatus
from nursing_core.domain.notes import NoteStatus
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


def _values(column: str, enum: type[StrEnum]) -> CheckConstraint:
    """A check that the column holds one of the enum's values (a null passes: add NOT NULL)."""
    listed = ", ".join(f"'{member.value}'" for member in enum)
    return CheckConstraint(f"{column} IN ({listed})", name=f"{column}_values")


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
    Column("version", Integer, nullable=False),
    # app_user also points back at facility: `use_alter` marks this key as the one added last.
    Column("updated_by", Uuid, ForeignKey("app_user.id", use_alter=True), nullable=True),
    _instant("updated_at"),
    UniqueConstraint("key"),
    _values("locale", Locale),
    _values("default_note_format", NoteFormat),
    CheckConstraint("unit_temperature IN ('Cel', '[degF]')", name="unit_temperature_values"),
    CheckConstraint(
        "unit_weight IS NULL OR unit_weight IN ('kg', '[lb_av]')", name="unit_weight_values"
    ),
    CheckConstraint("unit_volume IN ('mL')", name="unit_volume_values"),
    CheckConstraint("clock IN ('24h', '12h')", name="clock_values"),
    CheckConstraint("version > 0", name="version_positive"),
    CheckConstraint("cardinality(note_formats) > 0", name="has_a_note_format"),
    CheckConstraint("default_note_format = ANY (note_formats)", name="default_is_offered"),
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
    _values("role", Role),
    CheckConstraint("(facility_id IS NULL) = (role = 'admin')", name="admin_alone_has_no_facility"),
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
    UniqueConstraint("facility_id", "version"),
    CheckConstraint("version > 0", name="version_positive"),
    CheckConstraint("changed_by IS NOT NULL OR version = 1", name="author_unless_first"),
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
    CheckConstraint(
        "(shift_code IS NULL) = (shift_label IS NULL) "
        "AND (shift_code IS NULL) = (shift_starts_at IS NULL) "
        "AND (shift_code IS NULL) = (shift_ends_at IS NULL) "
        "AND (shift_code IS NULL) = (shift_date IS NULL) "
        "AND (shift_code IS NULL) = (shift_timezone IS NULL)",
        name="shift_all_or_none",
    ),
    CheckConstraint("expires_at > created_at", name="expires_after_creation"),
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
        "(status = 'signed') = (signed_by IS NOT NULL "
        "AND signed_at IS NOT NULL AND content_hash IS NOT NULL)",
        name="signature_only_when_signed",
    ),
    CheckConstraint(
        "(status = 'discarded') = (discarded_by IS NOT NULL AND discarded_at IS NOT NULL)",
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
    UniqueConstraint("rough_note_id"),
    _values("status", JobStatus),
    _values("failure", JobFailure),
    CheckConstraint("(status = 'failed') = (failure IS NOT NULL)", name="failure_only_when_failed"),
    CheckConstraint(
        "(status = 'succeeded') = (note_id IS NOT NULL)", name="note_only_when_succeeded"
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
)
