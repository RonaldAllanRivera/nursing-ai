"""The Makefile computes ports from PORT_OFFSET and rejects bad offsets."""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def run_make(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["make", "-s", *args],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_ports_follow_port_offset() -> None:
    result = run_make("ports", "PORT_OFFSET=2")
    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        "COMPOSE_PROJECT_NAME=nursing-ai-2",
        "WEB_PORT=5193",
        "API_PORT=8020",
        "DB_PORT=55452",
    ]


@pytest.mark.parametrize("offset", ["12", "x", ""])
def test_port_offset_must_be_0_to_9(offset: str) -> None:
    result = run_make("ports", f"PORT_OFFSET={offset}")
    assert result.returncode != 0
    assert "PORT_OFFSET must be a whole number from 0 to 9" in result.stderr
