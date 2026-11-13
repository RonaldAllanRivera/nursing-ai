"""The Makefile computes ports from PORT_OFFSET, rejects bad offsets and never leaks .env."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CANARY = "FAKE-canary"
FAKE_ENV = (
    f"ANTHROPIC_API_KEY=sk-ant-{CANARY}-123\nAI_MODE=replay\nAI_MONTHLY_CAP_USD=7\nPORT_OFFSET=0\n"
)


def run_make(
    *args: str, cwd: Path = ROOT, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    dropped = ("MAKEFLAGS", "MAKELEVEL", "PORT_OFFSET", "AI_MODE", "AI_MONTHLY_CAP_USD")
    env = {k: v for k, v in os.environ.items() if k not in dropped}
    env.update(extra_env or {})
    return subprocess.run(  # noqa: S603
        ["make", "-s", *args],  # noqa: S607
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    shutil.copy(ROOT / "Makefile", tmp_path / "Makefile")
    (tmp_path / ".env").write_text(FAKE_ENV)
    return tmp_path


def test_ports_follow_port_offset() -> None:
    result = run_make("ports", "PORT_OFFSET=2")
    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        "COMPOSE_PROJECT_NAME=nursing-ai-2",
        "WEB_PORT=5193",
        "API_PORT=8020",
        "DB_PORT=55452",
    ]


@pytest.mark.parametrize("offset", ["12", "x", "", "1 2", "1 x"])
def test_port_offset_must_be_0_to_9(offset: str) -> None:
    result = run_make("ports", f"PORT_OFFSET={offset}")
    assert result.returncode != 0
    assert "PORT_OFFSET must be a whole number from 0 to 9" in result.stderr


def test_spend_prints_the_three_facts_from_env(fake_repo: Path) -> None:
    result = run_make("spend", cwd=fake_repo)
    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        "AI_MODE=replay",
        "AI_MONTHLY_CAP_USD=7",
        "no AI usage recorded yet (no provider before P1)",
    ]


@pytest.mark.parametrize("target", ["ports", "help", "spend"])
def test_no_env_value_is_printed(fake_repo: Path, target: str) -> None:
    result = run_make(target, cwd=fake_repo)
    assert result.returncode == 0
    assert CANARY not in result.stdout + result.stderr


def test_environment_port_offset_beats_env_file(fake_repo: Path) -> None:
    result = run_make("ports", cwd=fake_repo, extra_env={"PORT_OFFSET": "1"})
    assert "API_PORT=8010" in result.stdout.splitlines()


def test_environment_ai_mode_beats_env_file(fake_repo: Path) -> None:
    result = run_make("spend", cwd=fake_repo, extra_env={"AI_MODE": "mock"})
    assert "AI_MODE=mock" in result.stdout.splitlines()


def test_help_lists_hooks_and_setup() -> None:
    lines = run_make("help").stdout.splitlines()
    hooks = next(line for line in lines if line.startswith("hooks "))
    assert "pre-commit and pre-push" in hooks
    setup = next(line for line in lines if line.startswith("setup "))
    assert "pnpm store flag" in setup


def test_setup_installs_python_web_tools_and_hooks_in_order() -> None:
    steps = run_make("-n", "setup").stdout.splitlines()
    assert steps[0] == "uv sync --all-packages"
    assert steps[1] == "pnpm -C web install --frozen-lockfile"
    assert steps[2] == "pnpm -C web exec playwright install chromium"
    assert any("install-tools" in step for step in steps[3:])
    assert steps[-1].endswith("pre-commit install")


def test_only_public_check_ci_passes_the_ci_flag() -> None:
    assert run_make("-n", "public-check-ci").stdout.split()[-1] == "--ci"
    assert "--ci" not in run_make("-n", "public-check").stdout


def test_accept_binary_needs_a_file() -> None:
    done = run_make("accept-binary")
    assert done.returncode != 0
    assert "FILE=" in done.stdout + done.stderr


def test_accept_binary_passes_the_file_to_the_script() -> None:
    steps = run_make("-n", "accept-binary", "FILE=web/public/fonts/a b.woff2").stdout
    assert "scripts/reviewed_binaries.py" in steps
    assert "'web/public/fonts/a b.woff2'" in steps
