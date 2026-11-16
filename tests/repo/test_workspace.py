import importlib
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest


@pytest.mark.parametrize("module", ["nursing_core", "nursing_api", "nursing_mcp", "nursing_evals"])
def test_package_imports(module: str) -> None:
    importlib.import_module(module)


def test_python_tools_ignore_claude_folder(repo_root: Path) -> None:
    cfg = tomllib.loads((repo_root / "pyproject.toml").read_text())["tool"]
    assert ".claude" in cfg["ruff"]["extend-exclude"]
    assert "**/.claude" in cfg["pyright"]["exclude"]
    assert ".claude" in cfg["pytest"]["ini_options"]["norecursedirs"]


def test_pytest_skips_the_hypothesis_folder(repo_root: Path) -> None:
    # norecursedirs replaces pytest's defaults, so Hypothesis warns unless its folder is listed.
    cfg = tomllib.loads((repo_root / "pyproject.toml").read_text())["tool"]
    assert ".hypothesis" in cfg["pytest"]["ini_options"]["norecursedirs"]


@pytest.mark.parametrize("name", ["vite.config.ts", "eslint.config.js", ".prettierignore"])
def test_web_tools_ignore_claude_folder(repo_root: Path, name: str) -> None:
    assert ".claude" in (repo_root / "web" / name).read_text()


@pytest.mark.parametrize(
    "path",
    [
        ".claude/settings.local.json",
        ".claude/worktrees/a/x.txt",
        "web/.claude/settings.local.json",
        "web/.claude/worktrees/x/y",
    ],
)
def test_gitignore_ignores_machine_local_claude_files_anywhere(
    repo_root: Path, tmp_path: Path, path: str
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)  # noqa: S607
    shutil.copy(repo_root / ".gitignore", tmp_path / ".gitignore")
    target = tmp_path / path
    target.parent.mkdir(parents=True)
    target.write_text("x\n")
    # Only the repo's own rules: no global ignore file.
    ignored = subprocess.run(  # noqa: S603
        ["git", "-c", "core.excludesFile=/dev/null", "check-ignore", "-q", path],  # noqa: S607
        cwd=tmp_path,
        check=False,
    )
    assert ignored.returncode == 0
