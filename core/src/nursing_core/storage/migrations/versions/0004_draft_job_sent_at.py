"""When a draft job's message was last sent to the queue (re-sending a lost one).

- `draft_job.sent_at` (nullable): set each time the API re-sends a job's message because it
  stayed `queued` (or ran out its lease while `running`) with no worker answering. A job never
  re-sent has none; its first send is counted from `created_at`.

Additive (one nullable column, no default, no rewrite), so it is safe on a live database. This
file is a fixed record, like 0001: it never imports `storage/tables.py`.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("draft_job", sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    raise NotImplementedError("a live migration is undone by a new one, never by a downgrade")
