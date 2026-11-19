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
    assert list(workflow["jobs"]) == ["check", "plan"]
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
    # The test-only sign-in route (throwaway Google-kind users) exists only when APP_ENV=test.
    assert {**job.get("env", {}), **up.get("env", {})}["APP_ENV"] == "test"


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


INFRA = ROOT / ".github" / "workflows" / "infra.yml"
DEPLOY = ROOT / ".github" / "workflows" / "deploy.yml"
AWS_CREDENTIALS = "aws-actions/configure-aws-credentials@"


def _runs(job: dict[str, Any]) -> list[str]:
    return [step["run"] for step in job["steps"] if "run" in step]


def _step(job: dict[str, Any], uses: str) -> dict[str, Any]:
    return next(step for step in job["steps"] if step.get("uses", "").startswith(uses))


def test_only_the_plan_and_deploy_jobs_can_ask_for_aws_credentials() -> None:
    # An id-token is what lets a job assume an AWS role; every other job runs without one.
    holders = {
        (path.name, name)
        for path in WORKFLOWS
        for name, job in _load(path)["jobs"].items()
        if job.get("permissions", {}).get("id-token") == "write"
    }
    assert holders == {("infra.yml", "plan"), ("deploy.yml", "deploy")}
    for path in WORKFLOWS:
        for job in _load(path)["jobs"].values():
            if any(s.get("uses", "").startswith(AWS_CREDENTIALS) for s in job["steps"]):
                assert job["permissions"] == {"contents": "read", "id-token": "write"}


def test_the_aws_sign_in_masks_the_account_id_in_the_public_logs() -> None:
    for path in (INFRA, DEPLOY):
        for job in _load(path)["jobs"].values():
            for step in job["steps"]:
                if step.get("uses", "").startswith(AWS_CREDENTIALS):
                    assert step["with"]["mask-aws-account-id"] is True, path.name
                    assert step["with"]["aws-region"] == "ap-southeast-2"


def test_the_plan_job_runs_only_for_this_repos_pull_requests_once_switched_on() -> None:
    job = _load(INFRA)["jobs"]["plan"]
    condition = " ".join(job["if"].split())
    # The plan role trusts `pull_request` tokens; a fork's pull request gets no token and
    # Dependabot gets no secrets, so neither runs the job. AWS_PLAN_ENABLED switches it on once
    # the bootstrap has made the role.
    assert "github.event_name == 'pull_request'" in condition
    assert "github.event.pull_request.head.repo.full_name == github.repository" in condition
    assert "github.actor != 'dependabot[bot]'" in condition
    assert "vars.AWS_PLAN_ENABLED == 'true'" in condition
    assert job["needs"] == "check"
    assert "environment" not in job
    sign_in = _step(job, AWS_CREDENTIALS)
    assert sign_in["with"]["role-to-assume"] == "${{ secrets.AWS_PLAN_ROLE_ARN }}"


def test_the_plan_never_refreshes_and_never_applies() -> None:
    job = _load(INFRA)["jobs"]["plan"]
    script = "\n".join(_runs(job))
    # A refresh decrypts every SSM parameter, which the plan role is denied (bootstrap).
    assert re.search(r"terraform -chdir=infra/live plan\b[^\n]*-refresh=false", script)
    assert "apply" not in script
    # It writes nothing, so it takes no lock: a pull request's plan must never make a deploy's
    # apply fail on "Error acquiring the state lock" (B-5).
    plan = re.search(r"terraform -chdir=infra/live plan\b[^\n]*", script)
    assert plan is not None
    assert "-lock=false" in plan.group(0)
    assert "-lock-timeout" not in plan.group(0)
    assert '-backend-config="bucket=$STATE_BUCKET"' in script
    checkout = _step(job, "actions/checkout@")
    assert checkout["with"]["persist-credentials"] is False


def test_deploy_runs_only_after_ci_passes_on_a_push_to_main() -> None:
    triggers = _triggers(DEPLOY)
    assert triggers == {
        "workflow_run": {"workflows": ["CI"], "types": ["completed"], "branches": ["main"]}
    }
    job = _load(DEPLOY)["jobs"]["deploy"]
    condition = " ".join(job["if"].split())
    assert "github.event.workflow_run.conclusion == 'success'" in condition
    assert "github.event.workflow_run.event == 'push'" in condition
    assert "vars.DEPLOY_ENABLED == 'true'" in condition
    # The commit CI checked, not whatever main points at by the time the reviewer approves.
    checkout = _step(job, "actions/checkout@")
    assert checkout["with"]["ref"] == "${{ github.event.workflow_run.head_sha }}"
    assert checkout["with"]["persist-credentials"] is False


def test_deploy_waits_for_the_production_reviewer_and_never_overlaps() -> None:
    workflow = _load(DEPLOY)
    job = workflow["jobs"]["deploy"]
    # The deploy role trusts only tokens from the production environment.
    assert job["environment"] == "production"
    concurrency = workflow["concurrency"]
    assert concurrency["cancel-in-progress"] is False
    assert "${{" not in concurrency["group"]
    sign_in = _step(job, AWS_CREDENTIALS)
    assert sign_in["with"]["role-to-assume"] == "${{ secrets.AWS_DEPLOY_ROLE_ARN }}"


def test_deploy_runs_the_same_script_as_make_deploy_and_prints_nothing_of_its_own() -> None:
    job = _load(DEPLOY)["jobs"]["deploy"]
    step = next(s for s in job["steps"] if "scripts/deploy.sh" in s.get("run", ""))
    assert re.search(r"(^|\n)scripts/deploy\.sh demo\n?$", step["run"])
    env = {**job.get("env", {}), **step.get("env", {})}
    assert env["DEPLOY_APPROVED"] == "yes"
    assert env["STATE_BUCKET"] == "${{ secrets.STATE_BUCKET }}"
    assert env["TF_VAR_alert_email"] == "${{ secrets.ALERT_EMAIL }}"
    # On a runner the default credential chain is the OIDC role, never a profile.
    assert "AWS_PROFILE" not in env
    # Actions logs of a public repository are public: the script decides what is printed.
    for run in _runs(job):
        assert not re.search(r"\b(echo|printenv|env|set -x|cat)\b", run), run


def test_the_deploy_tools_match_ci() -> None:
    job = _load(DEPLOY)["jobs"]["deploy"]
    terraform = _step(job, "hashicorp/setup-terraform@")
    assert terraform["with"] == {"terraform_version": "1.17.2", "terraform_wrapper": False}
    assert _step(job, "pnpm/action-setup@")["with"]["package_json_file"] == "web/package.json"
    assert "pnpm install --frozen-lockfile" in _runs(job)
