"""No region is hard-coded: timezone names live only in the presets, demo data, tests and docs.

Code reads the facility's profile. A timezone name anywhere else means a code path decided a
region by itself, which the second (US) demo facility exists to catch.
"""

import subprocess
from fnmatch import fnmatch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGION_NAMES = ("Asia/Manila", "America/Los_Angeles")
ALLOWED = (
    "core/src/nursing_core/domain/facility.py",
    "core/src/nursing_core/demo/*",
    "*/tests/*",
    "tests/*",
    "*.test.ts",
    "*.test.tsx",
    "web/e2e/*",
    "web/src/mocks/demo-api.ts",
    "docs/*",
    "README.md",
)


def files_naming_a_region(root: Path, paths: list[str]) -> list[str]:
    found: list[str] = []
    for path in paths:
        if any(fnmatch(path, pattern) for pattern in ALLOWED):
            continue
        try:
            text = (root / path).read_text(encoding="utf-8")
        except (UnicodeDecodeError, IsADirectoryError, FileNotFoundError):
            continue
        if any(name in text for name in REGION_NAMES):
            found.append(path)
    return found


def repo_files() -> list[str]:
    """Tracked files plus new ones a lane hasn't committed yet (ignored files left out)."""
    listing = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],  # noqa: S607
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [path for path in listing.split("\0") if path]


def test_timezone_names_only_in_presets_demo_data_and_tests() -> None:
    assert files_naming_a_region(ROOT, repo_files()) == []


def test_region_guard_catches_a_planted_name(tmp_path: Path) -> None:
    (tmp_path / "api" / "src").mkdir(parents=True)
    (tmp_path / "api" / "src" / "shifts.py").write_text('ZONE = "Asia/Manila"\n')
    (tmp_path / "core" / "tests").mkdir(parents=True)
    (tmp_path / "core" / "tests" / "test_x.py").write_text('ZONE = "Asia/Manila"\n')
    paths = ["api/src/shifts.py", "core/tests/test_x.py"]
    assert files_naming_a_region(tmp_path, paths) == ["api/src/shifts.py"]
