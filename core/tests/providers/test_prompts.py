"""The FDAR prompt: it loads by version, names its version and states the firm rules."""

import pytest
from nursing_core.prompts import FDAR_PROMPT_VERSION, load_prompt


def test_prompt_v1_loads_and_names_its_version() -> None:
    text = load_prompt(FDAR_PROMPT_VERSION)
    assert FDAR_PROMPT_VERSION == "fdar-v1"
    assert text.splitlines()[0] == "Prompt version: fdar-v1"


def test_unknown_prompt_version_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown prompt version"):
        load_prompt("fdar-v99")


@pytest.mark.parametrize(
    "rule",
    [
        "never invent",
        "source_quotes",
        "own_wording",
        "empty list",
        "never convert a unit",
        "[PATIENT_1]",
        "JSON schema",
    ],
)
def test_prompt_v1_states_each_rule(rule: str) -> None:
    assert rule in load_prompt(FDAR_PROMPT_VERSION)
