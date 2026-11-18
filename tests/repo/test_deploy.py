"""scripts/deploy.sh runs P2-19's steps in order, only when approved, and never reads a secret.

Nothing real runs: `aws`, `docker`, `terraform` and `pnpm` are one small stand-in script, linked
under those four names in a folder that is the whole of PATH (plus links to the plain tools the
script needs). Each call is appended to a log as one JSON line.
"""

import json
import os
import re
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "deploy.sh"
REAL_TOOLS = ("aws", "docker", "terraform", "pnpm")
# Plain tools the script and its stand-in use; linked into the test PATH so nothing else resolves.
PLAIN_TOOLS = (
    "bash",
    "sh",
    "env",
    "git",
    "python3",
    "date",
    "mktemp",
    "rm",
    "cat",
    "mkdir",
    "dirname",
    "basename",
    "tr",
    "head",
    "tail",
    "sed",
    "grep",
    "printf",
    "uname",
)
REGISTRY = "123456789012.dkr.ecr.ap-southeast-2.amazonaws.com"

# One stand-in for all four tools. FAKE_* variables steer what it answers.
STAND_IN = r"""#!/usr/bin/env python3
import json, os, sys

tool = os.path.basename(sys.argv[0])
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps({"tool": tool, "argv": args}) + "\n")

env = os.environ.get("TF_VAR_environment", "demo")
outputs = {
    "ops_function_name": f"nursing-ai-{env}-ops",
    "http_api_id": os.environ.get("FAKE_OUTPUT_API_ID", "abc123"),
    "dlq_name": f"nursing-ai-{env}-jobs-dlq",
    "web_bucket_name": f"nursing-ai-{env}-web",
    "distribution_id": "E123EXAMPLE",
}
if tool == "terraform" and "output" in args:
    if "-json" in args:
        print(json.dumps({
            "api_5xx": f"nursing-ai-{env}-api-5xx",
            "dead_jobs": f"nursing-ai-{env}-dead-jobs",
            "ai_spend": f"nursing-ai-{env}-ai-spend",
        }))
    else:
        name = args[-1]
        if name == "ops_function_name":
            applied = any(
                '"terraform"' in line and '"apply"' in line
                for line in open(os.environ["FAKE_LOG"])
            )
            if os.environ.get("FAKE_STATE_ENV"):
                outputs[name] = f"nursing-ai-{os.environ['FAKE_STATE_ENV']}-ops"
            elif (os.environ.get("FAKE_FIRST_DEPLOY") or os.environ.get("FAKE_NO_STATE")) \
                    and not applied:
                sys.stderr.write("Error: Output not found\n")
                sys.exit(1)
        sys.stdout.write(outputs[name])
elif tool == "aws":
    service, command = args[0], args[1]
    if service == "ecr" and command == "describe-repositories":
        print("@REGISTRY@/nursing-ai")
    elif service == "ecr":
        print("stand-in-registry-token")
    elif service == "lambda" and command == "get-function":
        error = os.environ.get("FAKE_GET_FUNCTION_ERROR")
        if os.environ.get("FAKE_FIRST_DEPLOY"):
            error = "ResourceNotFoundException"
        if error:
            sys.stderr.write(f"An error occurred ({error}) calling GetFunction\n")
            sys.exit(254)
        print(json.dumps({"Configuration": {"FunctionName": "x"}}))
    elif service == "lambda" and command == "invoke":
        task = json.loads(args[args.index("--payload") + 1])["task"]
        ok = task != os.environ.get("FAKE_FAIL_TASK")
        out = {"task": task, "ok": ok, "failed": [] if ok else ["database"]}
        if os.environ.get("FAKE_MISSING_OK") == task:
            out = {"errorMessage": "boom"}
        with open(args[-1], "w") as handle:
            json.dump(out, handle)
        print(json.dumps({"StatusCode": 200}))
    elif service == "cloudwatch" and command == "describe-alarms":
        names = args[args.index("--alarm-names") + 1 :]
        names = [n for n in names if not n.startswith("--")][:3]
        state = os.environ.get("FAKE_ALARM_STATE", "OK")
        alarms = []
        for name in names:
            dims = []
            if name.endswith("-api-5xx"):
                dims = [{"Name": "ApiId", "Value": os.environ.get("FAKE_ALARM_API_ID", "abc123")}]
            if name.endswith("-dead-jobs"):
                queue = os.environ.get("FAKE_ALARM_QUEUE", f"nursing-ai-{env}-jobs-dlq")
                dims = [{"Name": "QueueName", "Value": queue}]
            alarms.append({"AlarmName": name, "StateValue": state, "Dimensions": dims})
        print(json.dumps({"MetricAlarms": alarms}))
elif tool == "docker" and "login" in args:
    sys.stdin.read()
"""


@dataclass
class Call:
    tool: str
    argv: list[str]


@dataclass
class Run:
    result: subprocess.CompletedProcess[str]
    calls: list[Call]

    @property
    def aws(self) -> list[list[str]]:
        return [c.argv for c in self.calls if c.tool == "aws"]


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stand_in = bin_dir / "stand-in.py"
    stand_in.write_text(STAND_IN.replace("@REGISTRY@", REGISTRY))
    stand_in.chmod(stand_in.stat().st_mode | stat.S_IEXEC)
    for name in REAL_TOOLS:
        (bin_dir / name).symlink_to(stand_in.name)
    for name in PLAIN_TOOLS:
        found = shutil.which(name)
        if found:
            (bin_dir / name).symlink_to(found)
    return tmp_path


def run_deploy(
    sandbox: Path, *args: str, approved: bool = True, extra: dict[str, str] | None = None
) -> Run:
    log = sandbox / "calls.jsonl"
    env = {
        "PATH": str(sandbox / "bin"),
        "HOME": str(sandbox),
        "FAKE_LOG": str(log),
        "STATE_BUCKET": "nursing-ai-state-example",
    }
    if approved:
        env["DEPLOY_APPROVED"] = "yes"
    env.update(extra or {})
    result = subprocess.run(  # noqa: S603
        [str(SCRIPT), *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    lines = log.read_text().splitlines() if log.exists() else []
    calls = [Call(**json.loads(line)) for line in lines]
    return Run(result, calls)


def label(call: Call) -> str | None:
    """Name the deploy step a recorded call belongs to (None for plumbing)."""
    tool, argv = call.tool, call.argv
    if tool == "terraform":
        return next((f"terraform {w}" for w in ("init", "apply") if w in argv), None)
    if tool == "docker":
        return f"docker {argv[0]}" if argv[0] in ("build", "push") else None
    if tool == "pnpm":
        return "pnpm build"
    names = {
        ("lambda", "update-function-code"): "point ops function",
        ("lambda", "get-function"): "first-deploy check",
        ("s3", "sync"): "s3 sync",
        ("s3", "cp"): "s3 cp index",
        ("cloudfront", "create-invalidation"): "invalidate",
        ("cloudwatch", "describe-alarms"): "check alarms",
    }
    if argv[:2] == ["lambda", "invoke"]:
        return f"invoke {json.loads(argv[argv.index('--payload') + 1])['task']}"
    return names.get((argv[0], argv[1]))


def steps(run: Run) -> list[str]:
    return [s for c in run.calls if (s := label(c))]


NORMAL_DEMO = [
    "terraform init",
    "docker build",
    "docker push",
    "point ops function",
    "invoke migrate",
    "terraform apply",
    "invoke seed-demo",
    "invoke smoke",
    "pnpm build",
    "s3 sync",
    "s3 cp index",
    "invalidate",
    "check alarms",
]
FIRST_DEMO = [
    "terraform init",
    "first-deploy check",
    "docker build",
    "docker push",
    "terraform apply",
    "invoke migrate",
    "invoke seed-demo",
    "invoke smoke",
    "pnpm build",
    "s3 sync",
    "s3 cp index",
    "invalidate",
    "check alarms",
]


def test_deploy_runs_the_steps_in_order(sandbox: Path) -> None:
    run = run_deploy(sandbox, "demo")
    assert run.result.returncode == 0, run.result.stderr
    assert steps(run) == NORMAL_DEMO
    build = next(c.argv for c in run.calls if label(c) == "docker build")
    assert build[build.index("-f") + 1] == "api/Dockerfile"
    tag = build[build.index("-t") + 1]
    assert re.fullmatch(rf"{re.escape(REGISTRY)}/nursing-ai:[0-9a-f]{{12}}-\d{{14}}", tag)
    apply_call = next(c.argv for c in run.calls if label(c) == "terraform apply")
    assert apply_call.count("-var") == 1
    assert apply_call[apply_call.index("-var") + 1] == f"image_uri={tag}"
    push = next(c.argv for c in run.calls if label(c) == "docker push")
    assert push[-1] == tag
    update = next(a for a in run.aws if a[:2] == ["lambda", "update-function-code"])
    assert update[update.index("--function-name") + 1] == "nursing-ai-demo-ops"
    assert update[update.index("--image-uri") + 1] == tag
    printed = [ln for ln in run.result.stdout.splitlines() if ln.startswith("deploy: ")]
    assert "deploy: migrate" in printed


def test_deploy_uploads_index_uncached_and_assets_immutable(sandbox: Path) -> None:
    run = run_deploy(sandbox, "demo")
    assert run.result.returncode == 0, run.result.stderr
    sync = next(a for a in run.aws if a[:2] == ["s3", "sync"])
    assert sync[2:4] == ["web/dist", "s3://nursing-ai-demo-web"]
    assert "--delete" in sync
    assert sync[sync.index("--exclude") + 1] == "index.html"
    assert sync[sync.index("--cache-control") + 1] == "public, max-age=31536000, immutable"
    copy = next(a for a in run.aws if a[:2] == ["s3", "cp"])
    assert copy[2:4] == ["web/dist/index.html", "s3://nursing-ai-demo-web/index.html"]
    assert copy[copy.index("--cache-control") + 1] == "no-cache"
    invalidation = next(a for a in run.aws if a[:2] == ["cloudfront", "create-invalidation"])
    assert invalidation[invalidation.index("--distribution-id") + 1] == "E123EXAMPLE"
    assert invalidation[invalidation.index("--paths") + 1] == "/index.html"


def test_first_deploy_applies_before_it_migrates(sandbox: Path) -> None:
    run = run_deploy(sandbox, "demo", extra={"FAKE_FIRST_DEPLOY": "1"})
    assert run.result.returncode == 0, run.result.stderr
    assert steps(run) == FIRST_DEMO


def test_state_without_the_ops_function_and_a_live_function_is_not_a_first_deploy(
    sandbox: Path,
) -> None:
    run = run_deploy(sandbox, "demo", extra={"FAKE_NO_STATE": "1"})
    assert run.result.returncode == 0, run.result.stderr
    assert steps(run) == ["terraform init", "first-deploy check", *NORMAL_DEMO[1:]]


def test_a_state_that_names_the_ops_function_is_never_a_first_deploy(sandbox: Path) -> None:
    run = run_deploy(
        sandbox, "demo", extra={"FAKE_GET_FUNCTION_ERROR": "ResourceNotFoundException"}
    )
    assert run.result.returncode == 0, run.result.stderr
    assert steps(run) == NORMAL_DEMO


def test_a_get_function_error_other_than_not_found_stops_the_deploy(sandbox: Path) -> None:
    extra = {"FAKE_NO_STATE": "1", "FAKE_GET_FUNCTION_ERROR": "TooManyRequestsException"}
    run = run_deploy(sandbox, "demo", extra=extra)
    assert run.result.returncode != 0
    assert "TooManyRequestsException" in run.result.stderr
    assert steps(run) == ["terraform init", "first-deploy check"]


def test_state_of_another_environment_stops_before_the_build(sandbox: Path) -> None:
    run = run_deploy(sandbox, "demo", extra={"FAKE_STATE_ENV": "prod"})
    assert run.result.returncode != 0
    assert "nursing-ai-prod-ops" in run.result.stderr
    assert steps(run) == ["terraform init"]


def test_a_tfvars_environment_that_differs_stops_before_any_step(sandbox: Path) -> None:
    tfvars = sandbox / "terraform.tfvars"
    tfvars.write_text('alert_email = "a@example.com"\nenvironment = "prod"\n')
    run = run_deploy(sandbox, "demo", extra={"DEPLOY_TFVARS": str(tfvars)})
    assert run.result.returncode != 0
    assert "environment" in run.result.stderr
    assert run.calls == []
    tfvars.write_text('environment = "demo"\n')
    ok = run_deploy(sandbox, "demo", extra={"DEPLOY_TFVARS": str(tfvars)})
    assert ok.result.returncode == 0, ok.result.stderr


def test_the_log_shows_the_image_tag_but_not_the_registry_host(sandbox: Path) -> None:
    run = run_deploy(sandbox, "demo")
    assert run.result.returncode == 0, run.result.stderr
    assert re.search(r"deploy: .*[0-9a-f]{12}-\d{14}", run.result.stdout)
    assert REGISTRY not in run.result.stdout + run.result.stderr


def test_deploy_stops_when_migrate_fails(sandbox: Path) -> None:
    run = run_deploy(sandbox, "demo", extra={"FAKE_FAIL_TASK": "migrate"})
    assert run.result.returncode != 0
    assert "migrate" in run.result.stderr
    assert steps(run)[-1] == "invoke migrate"
    assert "terraform apply" not in steps(run)


def test_deploy_stops_when_a_task_answers_without_ok(sandbox: Path) -> None:
    run = run_deploy(sandbox, "demo", extra={"FAKE_MISSING_OK": "smoke"})
    assert run.result.returncode != 0
    assert "smoke" in run.result.stderr
    assert steps(run)[-1] == "invoke smoke"


@pytest.mark.parametrize("approval", [None, "no", "YES", ""])
def test_deploy_never_applies_without_approval(sandbox: Path, approval: str | None) -> None:
    extra = {} if approval is None else {"DEPLOY_APPROVED": approval}
    run = run_deploy(sandbox, "demo", approved=False, extra=extra)
    assert run.result.returncode != 0
    assert "DEPLOY_APPROVED" in run.result.stderr
    assert run.calls == []  # no build, no push, no init, no apply


@pytest.mark.parametrize("args", [(), ("staging",), ("demo", "extra"), ("",)])
def test_deploy_usage_exits_2_before_any_step(sandbox: Path, args: tuple[str, ...]) -> None:
    run = run_deploy(sandbox, *args)
    assert run.result.returncode == 2
    assert "usage" in run.result.stderr.lower()
    assert run.calls == []


def test_deploy_needs_the_state_bucket(sandbox: Path) -> None:
    run = run_deploy(sandbox, "demo", extra={"STATE_BUCKET": ""})
    assert run.result.returncode != 0
    assert "STATE_BUCKET" in run.result.stderr
    assert run.calls == []


def test_seed_demo_runs_only_for_demo(sandbox: Path) -> None:
    run = run_deploy(sandbox, "prod")
    assert run.result.returncode == 0, run.result.stderr
    assert steps(run) == [s for s in NORMAL_DEMO if s != "invoke seed-demo"]
    assert any("nursing-ai-prod-ops" in a for a in run.aws)


def test_deploy_never_reads_a_secret(sandbox: Path) -> None:
    for extra in ({}, {"FAKE_FIRST_DEPLOY": "1"}):
        run = run_deploy(sandbox, "demo", extra=extra)
        assert run.result.returncode == 0, run.result.stderr
        assert run.aws
        for argv in run.aws:
            assert argv[0] not in ("ssm", "secretsmanager", "kms")
            assert "--with-decryption" not in argv
        assert "stand-in-registry-token" not in run.result.stdout + run.result.stderr


@pytest.mark.parametrize(
    ("extra", "needle"),
    [
        ({"FAKE_ALARM_STATE": "ALARM"}, "nursing-ai-demo-api-5xx"),
        ({"FAKE_ALARM_API_ID": "someone-else"}, "api-5xx"),
        ({"FAKE_ALARM_QUEUE": "another-queue"}, "dead-jobs"),
    ],
)
def test_alarm_wiring_mismatch_fails_the_deploy(
    sandbox: Path, extra: dict[str, str], needle: str
) -> None:
    run = run_deploy(sandbox, "demo", extra=extra)
    assert run.result.returncode != 0
    assert needle in run.result.stderr
    assert steps(run)[-1] == "check alarms"


def test_insufficient_data_alarms_only_warn(sandbox: Path) -> None:
    run = run_deploy(sandbox, "demo", extra={"FAKE_ALARM_STATE": "INSUFFICIENT_DATA"})
    assert run.result.returncode == 0, run.result.stderr
    out = run.result.stdout + run.result.stderr
    assert "warning" in out.lower()
    assert "nursing-ai-demo-ai-spend" in out


def test_the_stand_ins_shadow_every_real_tool(sandbox: Path) -> None:
    path = str(sandbox / "bin")
    for name in REAL_TOOLS:
        found = shutil.which(name, path=path)
        assert found is not None
        assert Path(found).resolve() == (sandbox / "bin" / "stand-in.py").resolve()
    assert os.access(SCRIPT, os.X_OK)
