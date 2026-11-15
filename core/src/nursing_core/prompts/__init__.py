"""The system prompts sent to the model, one folder per prompt and version."""

from importlib import resources

FDAR_PROMPT_VERSION = "fdar-v1"

_PROMPT_FILES = {"fdar-v1": ("fdar", "v1", "system.md")}


def load_prompt(version: str) -> str:
    """The system prompt text for a version name such as "fdar-v1"."""
    try:
        parts = _PROMPT_FILES[version]
    except KeyError:
        raise ValueError("unknown prompt version") from None
    return resources.files(__package__).joinpath(*parts).read_text(encoding="utf-8")
