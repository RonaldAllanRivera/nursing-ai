"""The words the missing-items checklist looks for, in English, Taglish and US wording."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChecklistWords:
    dizzy: list[str]
    confused: list[str]
    safety: list[str]
    given: list[str]
    held: list[str]
    refused: list[str]


# Every facility uses every word. Treat this constant as read-only.
DEFAULT_WORDS = ChecklistWords(
    dizzy=["hilo", "nahihilo", "nahilo", "dizzy", "dizziness", "lightheaded", "light-headed"],
    confused=["confused", "confusion", "disoriented", "nalilito"],
    safety=[
        "side rails up",
        "siderails up",
        "bed alarm on",
        "call light within reach",
        "call bell within reach",
        "bed in low position",
        "bed in lowest position",
        "non-skid socks",
        "fall precautions",
        "fall precaution",
    ],
    given=["given", "administered", "binigay", "ibinigay"],
    held=["held", "withheld", "on hold"],
    refused=["refused", "declined", "tumanggi"],
)
