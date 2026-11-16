"""Only a signed note has a record, a discarded draft stays closed, a rough note stays as typed.

0001 made the record append-only and locked a signed note. Three writes still got through, though
no app path makes them: a version row for a note that isn't signed (a draft, a discarded draft, or
a hash, signer, time or version the note doesn't hold), a discarded draft turned back into a
draft, and a change to the rough note whose text the signed view shows. Each now raises with
SQLSTATE 23001 (restrict_violation) and a message that names the table and the refused action,
never a row's content.

Signing still works: `sign()` locks the note first and writes its version in the same
transaction, so the version matches the signed note it is checked against.

This file is a fixed record, like 0001: it never imports `storage/tables.py`.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION refuse_version_of_unsigned_note() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM note
                WHERE note.id = NEW.note_id
                    AND note.status = 'signed'
                    AND note.version = NEW.version
                    AND note.content_hash = NEW.content_hash
                    AND note.signed_by = NEW.signed_by
                    AND note.signed_at = NEW.signed_at
            ) THEN
                RAISE EXCEPTION '% is only for the version a signed note holds: % not allowed',
                    TG_TABLE_NAME, TG_OP
                    USING ERRCODE = 'restrict_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER note_version_only_of_a_signed_note BEFORE INSERT ON note_version "
        "FOR EACH ROW EXECUTE FUNCTION refuse_version_of_unsigned_note()"
    )
    op.execute(
        """
        CREATE FUNCTION refuse_change_of_discarded_note() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.status = 'discarded' THEN
                RAISE EXCEPTION '% is closed once discarded: % not allowed', TG_TABLE_NAME, TG_OP
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
    op.execute(
        "CREATE TRIGGER note_closed_once_discarded BEFORE UPDATE OR DELETE ON note "
        "FOR EACH ROW EXECUTE FUNCTION refuse_change_of_discarded_note()"
    )
    # The rough note is append-only, like the record: 0001's function refuses every change.
    op.execute(
        "CREATE TRIGGER rough_note_append_only BEFORE UPDATE OR DELETE ON rough_note "
        "FOR EACH ROW EXECUTE FUNCTION refuse_change_of_record()"
    )
    op.execute(
        "CREATE TRIGGER rough_note_no_truncate BEFORE TRUNCATE ON rough_note "
        "FOR EACH STATEMENT EXECUTE FUNCTION refuse_change_of_record()"
    )


def downgrade() -> None:
    raise NotImplementedError("the record's guards are never taken back")
