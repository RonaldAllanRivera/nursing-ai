"""The CI workflow is pinned and least-privilege."""

import re
from pathlib import Path
from typing import Any, cast

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))


def _load(path: Path) -> dict[str, Any]:
    data: object = yaml.safe_load(path.read_text())
    assert isinstance(data, dict)
    return cast("dict[str, Any]", data)


def test_every_action_is_pinned_to_a_commit_sha() -> None:
    assert WORKFLOWS
    uses = [
        step["uses"]
        for path in WORKFLOWS
        for job in _load(path)["jobs"].values()
        for step in job["steps"]
        if "uses" in step
    ]
    assert uses
    for ref in uses:
        assert re.search(r"@[0-9a-f]{40}$", ref), ref


def test_workflows_default_to_read_only_permissions() -> None:
    assert WORKFLOWS
    for path in WORKFLOWS:
        assert _load(path)["permissions"] == {"contents": "read"}, path.name


def test_public_check_job_reads_full_history() -> None:
    job = _load(ROOT / ".github" / "workflows" / "ci.yml")["jobs"]["public-check"]
    checkout = next(s for s in job["steps"] if s["uses"].startswith("actions/checkout@"))
    assert checkout["with"]["fetch-depth"] == 0
