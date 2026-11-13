from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header

from nursing_api.problems import problems
from nursing_api.routes import etag_header, not_built
from nursing_api.schemas import LineAction, NoteOut

router = APIRouter(prefix="/api/v1/notes", tags=["notes"])

IfMatch = Annotated[
    str | None, Header(alias="If-Match", description="Required: 428 without it, 412 when stale")
]
CHANGE = {200: {"headers": etag_header()}, **problems(401, 403, 404, 409, 412, 422, 428)}


@router.get(
    "/{note_id}",
    response_model=NoteOut,
    responses={200: {"headers": etag_header()}, **problems(401, 403, 404, 422)},
)
async def get_note(note_id: UUID) -> NoteOut:
    not_built()


@router.patch("/{note_id}/lines/{line_id}", response_model=NoteOut, responses=CHANGE)
async def act_on_line(
    note_id: UUID, line_id: str, action: LineAction, if_match: IfMatch = None
) -> NoteOut:
    """Confirm, edit, remove or restore one draft line."""
    not_built()


@router.post("/{note_id}/sign", response_model=NoteOut, responses=CHANGE)
async def sign_note(note_id: UUID, if_match: IfMatch = None) -> NoteOut:
    """Signs the draft: 409 review_incomplete lists the lines that still need the nurse."""
    not_built()


@router.post("/{note_id}/discard", response_model=NoteOut, responses=CHANGE)
async def discard_note(note_id: UUID, if_match: IfMatch = None) -> NoteOut:
    """Discards the draft; it never enters the record."""
    not_built()
