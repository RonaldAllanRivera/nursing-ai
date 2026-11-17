"""Invites and PINs, session gates, retried drafts and AI spend holds (the P2 contract).

- `facility.session_max_hours` (1 to 24, default 12): how long a sign-in lasts there.
- `facility_change.reset`: a demo reset back to the preset is a history row with no author.
- `app_user` learns who signs in with Google: an invited email (lowercase, unique), the Google
  subject bound at the first sign-in (unique), `persona`, `revoked_at`, `invited_by`, and the
  PIN's Argon2id hash with its failure count and lock time. A person who isn't a demo persona
  needs an email. P1 created only personas, so every existing row becomes one.
- `session` gains its CSRF token, when the PIN was last proved, the last activity and the wrong
  PINs typed in it. Sessions are disposable, so every existing one is deleted first: the new
  columns have no value to give an old row, and their people simply sign in again.
- `draft_job` can be retried: one rough note may now hold several jobs, but at most one that is
  queued, running or succeeded (a partial unique index replaces the plain one). `attempts` and
  `claimed_at` make a claim a lease, for SQS's at-least-once delivery.
- `ai_spend_hold`: the worst case of a live call in flight, counted against the monthly cap until
  its usage is recorded or it expires.

Additive apart from the session wipe and the swapped draft-job index, so it is safe on a live
database. This file is a fixed record, like 0001: it never imports `storage/tables.py`.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def _instant(name: str, *, nullable: bool = True) -> sa.Column[object]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    op.add_column(
        "facility",
        sa.Column("session_max_hours", sa.Integer(), nullable=False, server_default=sa.text("12")),
    )
    op.create_check_constraint(
        op.f("ck_facility_session_max_hours_range"),
        "facility",
        "session_max_hours BETWEEN 1 AND 24",
    )

    op.add_column(
        "facility_change",
        sa.Column("reset", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.drop_constraint(
        op.f("ck_facility_change_author_unless_first"), "facility_change", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_facility_change_author_unless_first_or_reset"),
        "facility_change",
        "changed_by IS NOT NULL OR version = 1 OR reset",
    )

    op.add_column("app_user", sa.Column("email", sa.Text(), nullable=True))
    op.add_column("app_user", sa.Column("google_sub", sa.Text(), nullable=True))
    op.add_column(
        "app_user",
        sa.Column("persona", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("app_user", _instant("revoked_at"))
    op.add_column("app_user", sa.Column("invited_by", sa.Uuid(), nullable=True))
    op.add_column("app_user", sa.Column("pin_hash", sa.Text(), nullable=True))
    op.add_column(
        "app_user",
        sa.Column("pin_failures", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column("app_user", _instant("pin_locked_at"))
    # P1 made only the demo personas, so every row so far is one.
    op.execute("UPDATE app_user SET persona = true")
    op.create_foreign_key(
        op.f("fk_app_user_invited_by_app_user"), "app_user", "app_user", ["invited_by"], ["id"]
    )
    op.create_unique_constraint(op.f("uq_app_user_email"), "app_user", ["email"])
    op.create_unique_constraint(op.f("uq_app_user_google_sub"), "app_user", ["google_sub"])
    op.create_check_constraint(
        op.f("ck_app_user_email_is_lowercase"), "app_user", "email = lower(email)"
    )
    op.create_check_constraint(
        op.f("ck_app_user_email_unless_persona"), "app_user", "persona OR email IS NOT NULL"
    )
    op.create_check_constraint(
        op.f("ck_app_user_pin_failures_not_negative"), "app_user", "pin_failures >= 0"
    )

    # A running API could add a session between the wipe and the new NOT NULL columns.
    op.execute("LOCK TABLE session IN ACCESS EXCLUSIVE MODE")
    op.execute("DELETE FROM session")
    op.add_column("session", sa.Column("csrf_token", sa.Text(), nullable=False))
    op.add_column("session", _instant("pin_verified_at"))
    op.add_column("session", _instant("last_active_at", nullable=False))
    op.add_column(
        "session",
        sa.Column("pin_failures", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.create_check_constraint(
        op.f("ck_session_pin_failures_not_negative"), "session", "pin_failures >= 0"
    )

    op.drop_constraint(op.f("uq_draft_job_rough_note_id"), "draft_job", type_="unique")
    op.create_index(
        op.f("uq_draft_job_rough_note_id_unless_failed"),
        "draft_job",
        ["rough_note_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running', 'succeeded')"),
    )
    op.add_column(
        "draft_job",
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column("draft_job", _instant("claimed_at"))
    op.create_check_constraint(
        op.f("ck_draft_job_attempts_not_negative"), "draft_job", "attempts >= 0"
    )

    op.create_table(
        "ai_spend_hold",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("amount_usd", sa.Numeric(12, 6), nullable=False),
        _instant("created_at", nullable=False),
        _instant("expires_at", nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_spend_hold")),
        sa.ForeignKeyConstraint(
            ["job_id"], ["draft_job.id"], name=op.f("fk_ai_spend_hold_job_id_draft_job")
        ),
        sa.CheckConstraint("amount_usd > 0", name=op.f("ck_ai_spend_hold_amount_positive")),
    )
    op.create_index(op.f("ix_ai_spend_hold_expires_at"), "ai_spend_hold", ["expires_at"])


def downgrade() -> None:
    raise NotImplementedError("a live migration is undone by a new one, never by a downgrade")
