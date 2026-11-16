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


def test_public_check_job_runs_the_ci_mode() -> None:
    job = _load(ROOT / ".github" / "workflows" / "ci.yml")["jobs"]["public-check"]
    runs = [step["run"] for step in job["steps"] if "run" in step]
    assert "make public-check-ci" in runs
    assert "make public-check" not in runs


def test_e2e_mock_job_runs_the_mock_journeys_after_the_web_checks() -> None:
    job = _load(ROOT / ".github" / "workflows" / "ci.yml")["jobs"]["e2e-mock"]
    assert job["needs"] == "web"
    runs = [step["run"] for step in job["steps"] if "run" in step]
    assert "pnpm exec playwright install --with-deps chromium" in runs
    assert "make e2e-mock" in runs
    upload = next(
        step for step in job["steps"] if step.get("uses", "").startswith("actions/upload-artifact@")
    )
    assert upload["if"] == "failure()"
    assert upload["with"]["path"] == "web/playwright-report"


def test_infra_workflow_checks_the_terraform_when_infra_changes() -> None:
    path = ROOT / ".github" / "workflows" / "infra.yml"
    workflow = _load(path)
    # PyYAML reads the bare key `on` as the boolean True (YAML 1.1).
    keys: dict[object, Any] = yaml.safe_load(path.read_text())
    triggers: dict[str, Any] = keys[True]
    # Never pull_request_target: a pull request's code must not run with the base repo's rights.
    assert set(triggers) == {"push", "pull_request"}
    for event in triggers.values():
        assert "infra/**" in event["paths"]
        assert ".github/workflows/infra.yml" in event["paths"]
    assert list(workflow["jobs"]) == ["check"]
    job = workflow["jobs"]["check"]
    # No id-token: the check job can never get AWS credentials.
    assert "permissions" not in job
    setup = next(
        step
        for step in job["steps"]
        if step.get("uses", "").startswith("hashicorp/setup-terraform@")
    )
    assert setup["with"]["terraform_version"] == "1.17.2"
    assert setup["with"]["terraform_wrapper"] is False
    runs = [step["run"] for step in job["steps"] if "run" in step]
    assert runs.index("make tools") < runs.index("make infra-check")


def test_dependabot_keeps_pgvector_at_a_version_aurora_offers() -> None:
    config = _load(ROOT / ".github" / "dependabot.yml")
    compose = next(u for u in config["updates"] if u["package-ecosystem"] == "docker-compose")
    ignored = {rule["dependency-name"]: set(rule["update-types"]) for rule in compose["ignore"]}
    assert ignored["pgvector/pgvector"] == {
        "version-update:semver-minor",
        "version-update:semver-patch",
    }


def test_e2e_job_runs_the_real_stack_in_replay_mode_on_a_named_web_port() -> None:
    job = _load(ROOT / ".github" / "workflows" / "ci.yml")["jobs"]["e2e"]
    env = {**job.get("env", {})}
    step = next(s for s in job["steps"] if s.get("run") == "pnpm e2e")
    env.update(step.get("env", {}))
    # The config refuses to run without WEB_PORT: another app could own the default port.
    assert env["WEB_PORT"]
    # The compose file reads AI_MODE, so the stack's own step must see replay too.
    up = next(s for s in job["steps"] if s.get("run", "").startswith("docker compose up"))
    assert {**job.get("env", {}), **up.get("env", {})}["AI_MODE"] == "replay"


def _triggers(path: Path) -> dict[str, Any]:
    # PyYAML reads the bare key `on` as the boolean True (YAML 1.1).
    keys: dict[object, Any] = yaml.safe_load(path.read_text())
    triggers = keys[True]
    assert isinstance(triggers, dict)
    return cast("dict[str, Any]", triggers)


def test_a_branch_with_an_open_pull_request_runs_once() -> None:
    # A push to any branch plus the pull request would run every check twice.
    triggers = _triggers(ROOT / ".github" / "workflows" / "ci.yml")
    assert set(triggers) == {"push", "pull_request"}
    assert triggers["push"] == {"branches": ["main"], "tags": ["v*"]}


def test_infra_workflow_pushes_only_run_on_main() -> None:
    triggers = _triggers(ROOT / ".github" / "workflows" / "infra.yml")
    assert triggers["push"]["branches"] == ["main"]
