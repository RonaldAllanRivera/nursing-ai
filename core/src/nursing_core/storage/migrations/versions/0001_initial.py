"""The first schema: facilities, people, patients, notes, the signed record and AI usage.

This file is a fixed record: it spells every table, constraint and trigger out and never
imports `storage/tables.py`, so a later edit to the table definitions can't change it. A test
compares the migrated database with `tables.metadata` to catch drift in either direction.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

HEX64 = "'^[0-9a-f]{64}$'"
UUID = sa.Uuid()
INSTANT = sa.DateTime(timezone=True)
JSONB = postgresql.JSONB()


def _in(table: str, column: str, values: list[str]) -> sa.CheckConstraint:
    listed = ", ".join(f"'{v}'" for v in values)
    return sa.CheckConstraint(f"{column} IN ({listed})", name=op.f(f"ck_{table}_{column}_values"))


def _check(table: str, name: str, condition: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(condition, name=op.f(f"ck_{table}_{name}"))


def _fk(table: str, column: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column], [f"{target}.id"], name=op.f(f"fk_{table}_{column}_{target}")
    )


def upgrade() -> None:
    op.create_table(
        "facility",
        sa.Column("id", UUID, nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("timezone", sa.Text(), nullable=False),
        sa.Column("locale", sa.Text(), nullable=False),
        sa.Column("day_starts_at", sa.Time(), nullable=False),
        sa.Column("note_formats", sa.ARRAY(sa.Text()), nullable=False),
        sa.Column("default_note_format", sa.Text(), nullable=False),
        sa.Column("unit_temperature", sa.Text(), nullable=False),
        sa.Column("unit_weight", sa.Text(), nullable=True),
        sa.Column("unit_volume", sa.Text(), nullable=False),
        sa.Column("clock", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_by", UUID, nullable=True),
        sa.Column("updated_at", INSTANT, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_facility")),
        sa.UniqueConstraint("key", name=op.f("uq_facility_key")),
        _in("facility", "locale", ["en-PH", "en-US"]),
        _in("facility", "default_note_format", ["fdar"]),
        _check("facility", "unit_temperature_values", "unit_temperature IN ('Cel', '[degF]')"),
        _check(
            "facility",
            "unit_weight_values",
            "unit_weight IS NULL OR unit_weight IN ('kg', '[lb_av]')",
        ),
        _check("facility", "unit_volume_values", "unit_volume IN ('mL')"),
        _check("facility", "clock_values", "clock IN ('24h', '12h')"),
        _check("facility", "version_positive", "version > 0"),
        _check("facility", "has_a_note_format", "cardinality(note_formats) > 0"),
        _check("facility", "default_is_offered", "default_note_format = ANY (note_formats)"),
    )

    op.create_table(
        "shift_definition",
        sa.Column("facility_id", UUID, nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("starts_local", sa.Time(), nullable=False),
        sa.Column("ends_local", sa.Time(), nullable=False),
        sa.Column("ink", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("facility_id", "position", name=op.f("pk_shift_definition")),
        _fk("shift_definition", "facility_id", "facility"),
        sa.UniqueConstraint(
            "facility_id", "code", name=op.f("uq_shift_definition_facility_id_code")
        ),
        _in("shift_definition", "ink", ["blue", "black", "red"]),
        _check("shift_definition", "position_not_negative", "position >= 0"),
        _check("shift_definition", "has_a_length", "starts_local <> ends_local"),
    )

    op.create_table(
        "app_user",
        sa.Column("id", UUID, nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("initials", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("facility_id", UUID, nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_app_user")),
        _fk("app_user", "facility_id", "facility"),
        _in("app_user", "role", ["staff_nurse", "head_nurse", "admin"]),
        _check(
            "app_user",
            "admin_alone_has_no_facility",
            "(facility_id IS NULL) = (role = 'admin')",
        ),
    )
    # The facility row names the admin who last edited it; app_user names its facility. The key
    # is added after both tables exist.
    op.create_foreign_key(
        op.f("fk_facility_updated_by_app_user"), "facility", "app_user", ["updated_by"], ["id"]
    )

    op.create_table(
        "facility_change",
        sa.Column("id", UUID, nullable=False),
        sa.Column("facility_id", UUID, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("changed_by", UUID, nullable=True),
        sa.Column("changed_at", INSTANT, nullable=False),
        sa.Column("settings", JSONB, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_facility_change")),
        _fk("facility_change", "facility_id", "facility"),
        _fk("facility_change", "changed_by", "app_user"),
        sa.UniqueConstraint(
            "facility_id", "version", name=op.f("uq_facility_change_facility_id_version")
        ),
        _check("facility_change", "version_positive", "version > 0"),
        _check("facility_change", "author_unless_first", "changed_by IS NOT NULL OR version = 1"),
    )

    op.create_table(
        "ward",
        sa.Column("id", UUID, nullable=False),
        sa.Column("facility_id", UUID, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ward")),
        _fk("ward", "facility_id", "facility"),
        sa.UniqueConstraint("facility_id", "name", name=op.f("uq_ward_facility_id_name")),
    )

    op.create_table(
        "bed",
        sa.Column("id", UUID, nullable=False),
        sa.Column("ward_id", UUID, nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bed")),
        _fk("bed", "ward_id", "ward"),
        sa.UniqueConstraint("ward_id", "label", name=op.f("uq_bed_ward_id_label")),
    )

    op.create_table(
        "patient",
        sa.Column("id", UUID, nullable=False),
        sa.Column("facility_id", UUID, nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("sex", sa.Text(), nullable=False),
        sa.Column("birth_date", sa.Date(), nullable=False),
        sa.Column("given_name", sa.Text(), nullable=False),
        sa.Column("middle_name", sa.Text(), nullable=True),
        sa.Column("family_name", sa.Text(), nullable=False),
        sa.Column("suffix", sa.Text(), nullable=True),
        sa.Column("nicknames", sa.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("record_number", sa.Text(), nullable=False),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("postal_code", sa.Text(), nullable=True),
        sa.Column("synthetic", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_patient")),
        _fk("patient", "facility_id", "facility"),
        sa.UniqueConstraint(
            "facility_id", "record_number", name=op.f("uq_patient_facility_id_record_number")
        ),
    )

    op.create_table(
        "patient_relative",
        sa.Column("patient_id", UUID, nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("relation", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("patient_id", "position", name=op.f("pk_patient_relative")),
        _fk("patient_relative", "patient_id", "patient"),
        _check("patient_relative", "position_not_negative", "position >= 0"),
    )

    op.create_table(
        "encounter",
        sa.Column("id", UUID, nullable=False),
        sa.Column("patient_id", UUID, nullable=False),
        sa.Column("bed_id", UUID, nullable=False),
        sa.Column("admitted_at", INSTANT, nullable=False),
        sa.Column("discharged_at", INSTANT, nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_encounter")),
        _fk("encounter", "patient_id", "patient"),
        _fk("encounter", "bed_id", "bed"),
        _check(
            "encounter", "stay_in_order", "discharged_at IS NULL OR discharged_at >= admitted_at"
        ),
    )

    op.create_table(
        "patient_context",
        sa.Column("encounter_id", UUID, nullable=False),
        sa.Column("context", JSONB, nullable=False),
        sa.Column("updated_at", INSTANT, nullable=False),
        sa.PrimaryKeyConstraint("encounter_id", name=op.f("pk_patient_context")),
        _fk("patient_context", "encounter_id", "encounter"),
    )

    op.create_table(
        "session",
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("shift_code", sa.Text(), nullable=True),
        sa.Column("shift_label", sa.Text(), nullable=True),
        sa.Column("shift_starts_at", INSTANT, nullable=True),
        sa.Column("shift_ends_at", INSTANT, nullable=True),
        sa.Column("shift_date", sa.Date(), nullable=True),
        sa.Column("shift_timezone", sa.Text(), nullable=True),
        sa.Column("created_at", INSTANT, nullable=False),
        sa.Column("expires_at", INSTANT, nullable=False),
        sa.PrimaryKeyConstraint("token_hash", name=op.f("pk_session")),
        _fk("session", "user_id", "app_user"),
        _check(
            "session",
            "shift_all_or_none",
            "(shift_code IS NULL) = (shift_label IS NULL) "
            "AND (shift_code IS NULL) = (shift_starts_at IS NULL) "
            "AND (shift_code IS NULL) = (shift_ends_at IS NULL) "
            "AND (shift_code IS NULL) = (shift_date IS NULL) "
            "AND (shift_code IS NULL) = (shift_timezone IS NULL)",
        ),
        _check("session", "expires_after_creation", "expires_at > created_at"),
    )

    op.create_table(
        "rough_note",
        sa.Column("id", UUID, nullable=False),
        sa.Column("encounter_id", UUID, nullable=False),
        sa.Column("author_id", UUID, nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("written_at", INSTANT, nullable=False),
        sa.Column("note_format", sa.Text(), nullable=False),
        sa.Column("shift_code", sa.Text(), nullable=False),
        sa.Column("shift_label", sa.Text(), nullable=False),
        sa.Column("shift_starts_at", INSTANT, nullable=False),
        sa.Column("shift_ends_at", INSTANT, nullable=False),
        sa.Column("shift_date", sa.Date(), nullable=False),
        sa.Column("shift_timezone", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("body_hash", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rough_note")),
        _fk("rough_note", "encounter_id", "encounter"),
        _fk("rough_note", "author_id", "app_user"),
        sa.UniqueConstraint(
            "author_id", "idempotency_key", name=op.f("uq_rough_note_author_id_idempotency_key")
        ),
        _in("rough_note", "note_format", ["fdar"]),
        _check("rough_note", "body_hash_is_hex", f"body_hash ~ {HEX64}"),
        _check("rough_note", "shift_has_a_length", "shift_ends_at > shift_starts_at"),
    )

    op.create_table(
        "note",
        sa.Column("id", UUID, nullable=False),
        sa.Column("rough_note_id", UUID, nullable=False),
        sa.Column("encounter_id", UUID, nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("draft", JSONB, nullable=False),
        sa.Column("checklist", JSONB, nullable=False),
        sa.Column("generation", JSONB, nullable=False),
        sa.Column("signed_by", UUID, nullable=True),
        sa.Column("signed_at", INSTANT, nullable=True),
        sa.Column("content_hash", sa.Text(), nullable=True),
        sa.Column("discarded_by", UUID, nullable=True),
        sa.Column("discarded_at", INSTANT, nullable=True),
        sa.Column("created_at", INSTANT, nullable=False),
        sa.Column("updated_at", INSTANT, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_note")),
        _fk("note", "rough_note_id", "rough_note"),
        _fk("note", "encounter_id", "encounter"),
        _fk("note", "signed_by", "app_user"),
        _fk("note", "discarded_by", "app_user"),
        sa.UniqueConstraint("rough_note_id", name=op.f("uq_note_rough_note_id")),
        _in("note", "status", ["draft", "signed", "discarded"]),
        _check("note", "version_positive", "version > 0"),
        _check("note", "content_hash_is_hex", f"content_hash ~ {HEX64}"),
        _check(
            "note",
            "signature_only_when_signed",
            "(status = 'signed') = (signed_by IS NOT NULL "
            "AND signed_at IS NOT NULL AND content_hash IS NOT NULL)",
        ),
        _check(
            "note",
            "discard_only_when_discarded",
            "(status = 'discarded') = (discarded_by IS NOT NULL AND discarded_at IS NOT NULL)",
        ),
    )

    op.create_table(
        "draft_job",
        sa.Column("id", UUID, nullable=False),
        sa.Column("rough_note_id", UUID, nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("failure", sa.Text(), nullable=True),
        sa.Column("note_id", UUID, nullable=True),
        sa.Column("created_at", INSTANT, nullable=False),
        sa.Column("updated_at", INSTANT, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_draft_job")),
        _fk("draft_job", "rough_note_id", "rough_note"),
        _fk("draft_job", "note_id", "note"),
        sa.UniqueConstraint("rough_note_id", name=op.f("uq_draft_job_rough_note_id")),
        _in("draft_job", "status", ["queued", "running", "succeeded", "failed"]),
        _in(
            "draft_job",
            "failure",
            [
                "ai_budget_reached",
                "model_refused",
                "invalid_output",
                "provider_error",
                "replay_missing",
            ],
        ),
        _check(
            "draft_job", "failure_only_when_failed", "(status = 'failed') = (failure IS NOT NULL)"
        ),
        _check(
            "draft_job",
            "note_only_when_succeeded",
            "(status = 'succeeded') = (note_id IS NOT NULL)",
        ),
    )

    op.create_table(
        "note_version",
        sa.Column("id", UUID, nullable=False),
        sa.Column("note_id", UUID, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", JSONB, nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("signed_by", UUID, nullable=False),
        sa.Column("signed_at", INSTANT, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_note_version")),
        _fk("note_version", "note_id", "note"),
        _fk("note_version", "signed_by", "app_user"),
        sa.UniqueConstraint("note_id", name=op.f("uq_note_version_note_id")),
        _check("note_version", "version_positive", "version > 0"),
        _check("note_version", "content_hash_is_hex", f"content_hash ~ {HEX64}"),
    )

    op.create_table(
        "ai_usage",
        sa.Column("id", UUID, nullable=False),
        sa.Column("job_id", UUID, nullable=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("created_at", INSTANT, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_usage")),
        _fk("ai_usage", "job_id", "draft_job"),
        _check("ai_usage", "provider_values", "provider IN ('fake', 'replay', 'anthropic')"),
        _check("ai_usage", "tokens_not_negative", "input_tokens >= 0 AND output_tokens >= 0"),
        _check("ai_usage", "cost_not_negative", "cost_usd >= 0"),
    )

    _lock_the_record()


def _lock_the_record() -> None:
    """Triggers that make the signed record and the settings history append-only.

    Each raises with SQLSTATE 23001 (restrict_violation) and a message that names the table and
    the refused action, never a row's content. TRUNCATE skips row triggers, so the two
    append-only tables also get a statement-level trigger for it.
    """
    op.execute(
        """
        CREATE FUNCTION refuse_change_of_record() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only: % not allowed', TG_TABLE_NAME, TG_OP
                USING ERRCODE = 'restrict_violation';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION refuse_change_of_signed_note() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.status = 'signed' THEN
                RAISE EXCEPTION '% is locked once signed: % not allowed', TG_TABLE_NAME, TG_OP
                    USING ERRCODE = 'restrict_violation';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    for table in ("note_version", "facility_change"):
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION refuse_change_of_record()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION refuse_change_of_record()"
        )
    op.execute(
        "CREATE TRIGGER note_locked_once_signed BEFORE UPDATE OR DELETE ON note "
        "FOR EACH ROW EXECUTE FUNCTION refuse_change_of_signed_note()"
    )


def downgrade() -> None:
    raise NotImplementedError("the first migration has nothing to go back to")
