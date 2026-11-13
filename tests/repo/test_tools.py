"""Pinned tools and the safety coverage floor."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PINS = ("gitleaks", "tflint", "trivy")
SAFETY_PATTERNS = (
    "*/nursing_core/domain/*",
    "*/nursing_core/pipeline/*",
    "*/nursing_core/storage/signing.py",
)


def pin(tool: str) -> dict[str, str]:
    text = (ROOT / "scripts" / f"{tool}.pin").read_text()
    return dict(re.findall(r"^([A-Z0-9_]+)=(\S+)$", text, re.MULTILINE))


@pytest.mark.parametrize("tool", PINS)
def test_tool_pins_are_exact_versions_with_sha256(tool: str) -> None:
    values = pin(tool)
    prefix = tool.upper()
    assert re.fullmatch(r"\d+\.\d+\.\d+", values[f"{prefix}_VERSION"])
    assert re.fullmatch(r"[0-9a-f]{64}", values[f"{prefix}_SHA256"])


def test_trivy_pin_is_past_every_known_bad_or_unpatched_release() -> None:
    # The March 2026 compromise published v0.69.4 (and Docker images 0.69.5 and 0.69.6);
    # the later path-traversal and tar-bomb advisories are fixed in 0.72.0.
    version = tuple(int(part) for part in pin("trivy")["TRIVY_VERSION"].split("."))
    assert version >= (0, 72, 0)


@pytest.mark.parametrize("tool", PINS)
def test_install_script_installs_every_pinned_tool(tool: str) -> None:
    script = (ROOT / "scripts" / "install-tools.sh").read_text()
    assert f"read_pin {tool}" in script
    assert "sha256sum -c" in script


def test_safety_coverage_floor_in_make_and_ci() -> None:
    for path in ("Makefile", ".github/workflows/ci.yml"):
        text = (ROOT / path).read_text()
        assert "--fail-under=90" in text, path
        assert all(pattern in text for pattern in SAFETY_PATTERNS), path
