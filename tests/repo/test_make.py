"""The Makefile computes ports from PORT_OFFSET, rejects bad offsets and never leaks .env."""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CANARY = "FAKE-canary"
FAKE_ENV = (
    f"ANTHROPIC_API_KEY=sk-ant-{CANARY}-123\nAI_MODE=replay\nAI_MONTHLY_CAP_USD=7\nPORT_OFFSET=0\n"
)
# Stands in for uv: prints what the recipe handed it ("unset" when a variable is absent).
FAKE_UV = """#!/bin/sh
echo "DATABASE_URL=${DATABASE_URL-unset}"
echo "AI_MODE=${AI_MODE-unset}"
echo "AI_MONTHLY_CAP_USD=${AI_MONTHLY_CAP_USD-unset}"
echo "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY-unset}"
echo "uv $*"
"""
LOCAL_URL = "postgresql+asyncpg://app:localdev@127.0.0.1:55432/app"


def run_make(
    *args: str, cwd: Path = ROOT, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    dropped = (
        "MAKEFLAGS",
        "MAKELEVEL",
        "PORT_OFFSET",
        "AI_MODE",
        "AI_MONTHLY_CAP_USD",
        "ANTHROPIC_API_KEY",
        "DATABASE_URL",
        "POSTGRES_PASSWORD",
    )
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
    # The Makefile puts .tools/bin first on PATH, so this uv stands in for the real one.
    fake_bin = tmp_path / ".tools" / "bin"
    fake_bin.mkdir(parents=True)
    uv = fake_bin / "uv"
    uv.write_text(FAKE_UV)
    uv.chmod(0o755)
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


def test_spend_runs_the_report_on_the_local_database_with_the_env_settings(
    fake_repo: Path,
) -> None:
    result = run_make("spend", cwd=fake_repo)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        f"DATABASE_URL={LOCAL_URL}",
        "AI_MODE=replay",
        "AI_MONTHLY_CAP_USD=7",
        "ANTHROPIC_API_KEY=unset",
        "uv run python -m nursing_api.spend",
    ]


@pytest.mark.parametrize("shell_env", [{}, {"AI_MONTHLY_CAP_USD": ""}])
def test_spend_leaves_an_empty_cap_unset(fake_repo: Path, shell_env: dict[str, str]) -> None:
    # `.env.example` ships `AI_MONTHLY_CAP_USD=`; an empty string makes the app's settings invalid.
    (fake_repo / ".env").write_text("AI_MONTHLY_CAP_USD=\n")
    lines = run_make("spend", cwd=fake_repo, extra_env=shell_env).stdout.splitlines()
    assert "AI_MONTHLY_CAP_USD=unset" in lines
    assert "AI_MODE=mock" in lines


@pytest.mark.parametrize(
    ("target", "module"),
    [("migrate", "nursing_core.storage.migrate"), ("seed", "nursing_core.storage.seed")],
)
def test_database_targets_run_on_the_offset_database_with_the_env_password(
    fake_repo: Path, target: str, module: str
) -> None:
    (fake_repo / ".env").write_text("POSTGRES_PASSWORD=not-the-default\n")
    result = run_make(target, "PORT_OFFSET=2", cwd=fake_repo)
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert "DATABASE_URL=postgresql+asyncpg://app:not-the-default@127.0.0.1:55452/app" in lines
    assert lines[-1] == f"uv run python -m {module}"


def test_seed_migrates_first(fake_repo: Path) -> None:
    lines = run_make("seed", cwd=fake_repo).stdout.splitlines()
    assert [line for line in lines if line.startswith("uv ")] == [
        "uv run python -m nursing_core.storage.migrate",
        "uv run python -m nursing_core.storage.seed",
    ]


@pytest.mark.parametrize("target", ["spend", "migrate", "seed"])
def test_database_targets_never_pass_the_api_key(fake_repo: Path, target: str) -> None:
    # Not from .env (the fixture's), and not from a shell that exports one either.
    result = run_make(
        target, cwd=fake_repo, extra_env={"ANTHROPIC_API_KEY": f"sk-ant-{CANARY}-456"}
    )
    assert result.returncode == 0, result.stderr
    assert "ANTHROPIC_API_KEY=unset" in result.stdout.splitlines()
    assert CANARY not in result.stdout + result.stderr


def test_help_lists_the_database_targets() -> None:
    lines = run_make("help").stdout.splitlines()
    for target in ("migrate", "seed", "spend"):
        assert any(line.startswith(f"{target} ") for line in lines), target
    spend = next(line for line in lines if line.startswith("spend "))
    assert "this month's AI spend" in spend


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


def test_infra_check_runs_the_terraform_check_script() -> None:
    assert run_make("-n", "infra-check").stdout.splitlines() == ["infra/scripts/check.sh"]
    help_line = next(line for line in run_make("help").stdout.splitlines() if "infra-check" in line)
    assert "Terraform" in help_line


def test_check_leaves_out_the_terraform_check() -> None:
    # Its first run downloads several hundred MB of providers, so it is its own target.
    assert "infra/scripts/check.sh" not in run_make("-n", "check").stdout


def test_e2e_mock_runs_the_mock_journeys_on_the_offset_web_port(fake_repo: Path) -> None:
    # The Makefile puts .tools/bin first on PATH, so this pnpm stands in for the real one.
    pnpm = fake_repo / ".tools" / "bin" / "pnpm"
    pnpm.write_text('#!/bin/sh\necho "WEB_PORT=$WEB_PORT pnpm $*"\n')
    pnpm.chmod(0o755)
    result = run_make("e2e-mock", "PORT_OFFSET=1", cwd=fake_repo)
    assert result.returncode == 0, result.stderr
    # One command and no `up`: the mock API runs in the browser, so no stack starts.
    assert result.stdout.splitlines() == ["WEB_PORT=5183 pnpm -C web e2e:mock"]


def test_record_replays_passes_the_key_only_through_the_environment(fake_repo: Path) -> None:
    key = f"sk-ant-{CANARY}-123"  # the fixture's .env value
    result = run_make("record-replays", "AI_MODE=live", cwd=fake_repo)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        f"DATABASE_URL={LOCAL_URL}",
        "AI_MODE=live",
        "AI_MONTHLY_CAP_USD=7",
        f"ANTHROPIC_API_KEY={key}",
        "uv run python -m nursing_api.record_replays",
    ]
    # Neither a dry run nor the process list (the command line) can show it.
    dry = run_make("-n", "record-replays", "AI_MODE=live", cwd=fake_repo)
    assert key not in dry.stdout + dry.stderr
    assert "record_replays" in dry.stdout


def test_record_replays_prefers_the_shells_key_to_the_env_files(fake_repo: Path) -> None:
    result = run_make(
        "record-replays", cwd=fake_repo, extra_env={"ANTHROPIC_API_KEY": f"sk-ant-{CANARY}-456"}
    )
    assert f"ANTHROPIC_API_KEY=sk-ant-{CANARY}-456" in result.stdout.splitlines()


def test_help_says_record_replays_costs_money() -> None:
    line = next(
        row for row in run_make("help").stdout.splitlines() if row.startswith("record-replays")
    )
    assert "calls the live model and costs money" in line


def test_readme_media_runs_the_media_script_and_says_what_it_needs() -> None:
    result = run_make("-n", "readme-media", "PORT_OFFSET=1")
    assert result.returncode == 0, result.stderr
    assert "playwright.readme.config.ts" in result.stdout
    helped = run_make("help").stdout
    line = next(row for row in helped.splitlines() if row.startswith("readme-media"))
    assert "replay" in line
    assert "docs/media" in line


def test_e2e_never_runs_the_media_script() -> None:
    result = run_make("-n", "e2e", "PORT_OFFSET=1")
    assert result.returncode == 0, result.stderr
    assert "readme" not in result.stdout
    config = (ROOT / "web" / "playwright.config.ts").read_text()
    assert "readme/**" in config


def test_every_package_and_the_app_carry_one_version() -> None:
    versions = {
        name: re.search(r'^version = "([^"]+)"', (ROOT / name / "pyproject.toml").read_text(), re.M)
        for name in ("core", "api", "mcp", "evals")
    }
    found = {name: m.group(1) if m else None for name, m in versions.items()}
    app = re.search(r'version="([^"]+)"', (ROOT / "api/src/nursing_api/app.py").read_text())
    found["app"] = app.group(1) if app else None
    assert len(set(found.values())) == 1, found


# Stands in for scripts/deploy.sh: prints its arguments and what the recipe handed it.
FAKE_DEPLOY = """#!/bin/sh
echo "deploy.sh $*"
echo "DEPLOY_APPROVED=${DEPLOY_APPROVED-unset}"
echo "AWS_PROFILE=${AWS_PROFILE-unset}"
echo "AWS_REGION=${AWS_REGION-unset}"
echo "STATE_BUCKET=${STATE_BUCKET-unset}"
echo "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY-unset}"
"""
DEPLOY_DROPPED = ("AWS_PROFILE", "AWS_REGION", "STATE_BUCKET", "DEPLOY_APPROVED")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],  # noqa: S607
        cwd=repo,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def deploy_repo(fake_repo: Path) -> Path:
    """A clean git checkout on main with the Makefile and a stand-in deploy script."""
    script = fake_repo / "scripts" / "deploy.sh"
    script.parent.mkdir()
    script.write_text(FAKE_DEPLOY)
    script.chmod(0o755)
    (fake_repo / ".gitignore").write_text(".env\n.tools/\n")
    _git(fake_repo, "init", "-q", "-b", "main")
    _git(fake_repo, "add", ".")
    _git(fake_repo, "commit", "-q", "-m", "init")
    return fake_repo


def make_deploy(
    repo: Path, typed: str, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in (*DEPLOY_DROPPED, "MAKEFLAGS", "MAKELEVEL", "ANTHROPIC_API_KEY")
    }
    env.update(extra_env or {})
    return subprocess.run(
        ["make", "-s", "deploy"],  # noqa: S607
        cwd=repo,
        env=env,
        input=typed,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("name", ["demo", "prod"])
def test_deploy_runs_the_script_for_the_typed_environment(deploy_repo: Path, name: str) -> None:
    result = make_deploy(deploy_repo, f"{name}\n", {"STATE_BUCKET": "state-bucket-x"})
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert f"deploy.sh {name}" in lines
    assert "DEPLOY_APPROVED=yes" in lines
    # Allan's `aws login` profile and the stack's region (the global constraints).
    assert "AWS_PROFILE=nursing-ai" in lines
    assert "AWS_REGION=ap-southeast-2" in lines
    assert "STATE_BUCKET=state-bucket-x" in lines


def test_deploy_reads_the_state_bucket_from_env_file_and_keeps_a_shell_profile(
    deploy_repo: Path,
) -> None:
    (deploy_repo / ".env").write_text(f"{FAKE_ENV}STATE_BUCKET=from-env-file\n")
    result = make_deploy(deploy_repo, "demo\n", {"AWS_PROFILE": "other-profile"})
    lines = result.stdout.splitlines()
    assert "STATE_BUCKET=from-env-file" in lines
    assert "AWS_PROFILE=other-profile" in lines


@pytest.mark.parametrize("typed", ["", "\n", "Demo\n", "yes\n", "demo prod\n", "staging\n"])
def test_deploy_runs_nothing_unless_the_name_is_typed_exactly(
    deploy_repo: Path, typed: str
) -> None:
    result = make_deploy(deploy_repo, typed, {"DEPLOY_APPROVED": "yes"})
    assert result.returncode != 0
    assert "deploy.sh" not in result.stdout
    assert "nothing was run" in result.stderr


@pytest.mark.parametrize("change", ["modified", "untracked"])
def test_deploy_refuses_a_dirty_tree(deploy_repo: Path, change: str) -> None:
    # The image is tagged with HEAD's commit: an uncommitted change would ship under a clean name.
    if change == "modified":
        (deploy_repo / "Makefile").write_text((deploy_repo / "Makefile").read_text() + "\n")
    else:
        (deploy_repo / "stray.txt").write_text("x\n")
    result = make_deploy(deploy_repo, "demo\n")
    assert result.returncode != 0
    assert "deploy.sh" not in result.stdout
    assert "commit" in result.stderr
    assert "nothing was run" in result.stderr


def test_deploy_runs_from_main_only(deploy_repo: Path) -> None:
    _git(deploy_repo, "switch", "-q", "-c", "feature")
    result = make_deploy(deploy_repo, "demo\n")
    assert result.returncode != 0
    assert "deploy.sh" not in result.stdout
    assert "main" in result.stderr


def test_deploy_never_passes_the_api_key(deploy_repo: Path) -> None:
    result = make_deploy(deploy_repo, "demo\n", {"ANTHROPIC_API_KEY": f"sk-ant-{CANARY}-789"})
    assert result.returncode == 0, result.stderr
    assert "ANTHROPIC_API_KEY=unset" in result.stdout.splitlines()
    assert CANARY not in result.stdout + result.stderr


def test_help_says_deploy_costs_money() -> None:
    lines = run_make("help").stdout.splitlines()
    deploy = next(line for line in lines if line.startswith("deploy "))
    assert "costs money" in deploy
