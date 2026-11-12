import importlib
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
