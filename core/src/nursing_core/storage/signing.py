"""The pure step before a signature is stored: what the nurse signs, hashed.

Kept apart from the repository so it can be tested without a database, and under the safety
coverage floor: this is the one place a draft becomes the record.
"""

from datetime import datetime
from uuid import UUID

from nursing_core.domain.hashing import SignedNote, content_hash, signed_content
from nursing_core.domain.notes import Note, RoughNote, Signature


def signed_record(
    note: Note, rough_note: RoughNote, signed_by: UUID, signed_at: datetime
) -> SignedNote:
    """The record a signature writes: the reviewed lines (removed ones left out, no AI text),
    their hash, and who signed and when.

    Raises ReviewIncomplete (with the line ids) while any line still needs the nurse, NoteLocked
    when the note isn't a draft, and ValueError for a removed focus line.
    """
    content = signed_content(note, rough_note, signed_by, signed_at)
    signature = Signature(
        signed_by=content.signed_by,
        signed_at=content.signed_at,
        content_hash=content_hash(content),
    )
    return SignedNote(note_id=note.id, content=content, signature=signature)
