"""The four things a nurse does to one draft line, as pure steps on the draft."""

from collections.abc import Callable

from nursing_core.domain.errors import NotFound
from nursing_core.domain.notes import DraftLine, FdarDraft, FdarEntry, FdarSection, LineReview
from nursing_core.domain.units import UnitDefaults
from nursing_core.pipeline.text import prepare
from nursing_core.pipeline.verify import recheck_line, restore_line

from nursing_api.problems import ActionRefused
from nursing_api.schemas import ConfirmLine, EditLine, RemoveLine, RestoreLine


def _confirm(line: DraftLine) -> DraftLine:
    if line.review is LineReview.REMOVED:
        raise ActionRefused("restore the line first")
    # An edited or confirmed line stays as it is: "edited" is the only record of a rewrite.
    if line.review is LineReview.PENDING:
        return line.model_copy(update={"review": LineReview.CONFIRMED})
    return line


def _remove(line: DraftLine) -> DraftLine:
    if line.section is FdarSection.FOCUS:
        raise ActionRefused("a focus line can be edited but not removed")
    return line.model_copy(update={"review": LineReview.REMOVED})


def apply_line_action(
    draft: FdarDraft,
    line_id: str,
    action: ConfirmLine | EditLine | RemoveLine | RestoreLine,
    rough_text: str,
    units: UnitDefaults,
) -> FdarDraft:
    """The draft after the action; the same draft (equal) when the action changes nothing.

    `units` are the facility's units in force now. Raises NotFound for an unknown line id and
    ActionRefused when the action isn't allowed on that line.
    """
    note = prepare(rough_text)
    change: Callable[[DraftLine], DraftLine]
    match action:
        case ConfirmLine():
            change = _confirm
        case EditLine(text=text):
            change = lambda line: recheck_line(line, text, note, units)  # noqa: E731
        case RemoveLine():
            change = _remove
        case RestoreLine():
            change = lambda line: restore_line(line, note, units)  # noqa: E731

    if line_id not in {line.id for line in draft.lines()}:
        raise NotFound("no such line")

    def one(line: DraftLine) -> DraftLine:
        return change(line) if line.id == line_id else line

    return FdarDraft(
        entries=[
            FdarEntry(
                focus=one(entry.focus),
                data=[one(line) for line in entry.data],
                action=[one(line) for line in entry.action],
                response=[one(line) for line in entry.response],
            )
            for entry in draft.entries
        ]
    )
