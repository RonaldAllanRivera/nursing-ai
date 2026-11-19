"""scripts/deploy.sh runs the deploy steps in order, only when approved, and never reads a secret.

Nothing real runs: `aws`, `docker`, `terraform` and `pnpm` are one small stand-in script, linked
under those four names in a folder that is the whole of PATH (plus links to the plain tools the
script needs). Each call is appended to a log as one JSON line.
"""

import fnmatch
import itertools
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
    aws_env = sorted(k for k in os.environ if k.startswith(("AWS_", "ACTIONS_ID_TOKEN_REQUEST_")))
    log.write(json.dumps({"tool": tool, "argv": args, "aws_env": aws_env}) + "\n")

env = os.environ.get("TF_VAR_environment", "demo")
outputs = {
    "ops_function_name": f"nursing-ai-{env}-ops",
    "http_api_id": os.environ.get("FAKE_OUTPUT_API_ID", "abc123"),
    "dlq_name": f"nursing-ai-{env}-jobs-dlq",
    "web_bucket_name": f"nursing-ai-{env}-web",
    "distribution_id": "E123EXAMPLE",
}
fail_with = os.environ.get("FAKE_FAIL_MESSAGE", "")
if tool == "terraform" and "apply" in args and os.environ.get("FAKE_APPLY_PRINTS"):
    print(fail_with)
    sys.stderr.write(fail_with + "\n")
    if os.environ.get("FAKE_APPLY_FAILS"):
        sys.exit(1)
if tool == "terraform" and "init" in args and os.environ.get("FAKE_INIT_FAILS"):
    sys.stderr.write(fail_with + "\n")
    sys.exit(1)
if tool == "pnpm" and os.environ.get("FAKE_PNPM_FAILS"):
    sys.stderr.write(fail_with + "\n")
    sys.exit(1)
if tool == "docker" and os.environ.get("FAKE_DOCKER_FAIL") in args:
    sys.stderr.write(fail_with + "\n")
    sys.exit(1)
if tool == "aws" and os.environ.get("FAKE_AWS_FAIL") == " ".join(args[:2]):
    sys.stderr.write(fail_with + "\n")
    sys.exit(254)
if tool == "terraform" and "state" in args:
    if os.environ.get("FAKE_STATE_LIST_FAILS"):
        sys.stderr.write("Error: Failed to load state\n")
        sys.exit(1)
    nothing_applied = os.environ.get("FAKE_FIRST_DEPLOY") or os.environ.get("FAKE_NO_STATE")
    empty = nothing_applied and not os.environ.get("FAKE_STATE_RESOURCES")
    if not empty:
        print("aws_lambda_function.ops")
elif tool == "terraform" and "output" in args:
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
        if os.environ.get("FAKE_GET_FUNCTION_MESSAGE"):
            sys.stderr.write(os.environ["FAKE_GET_FUNCTION_MESSAGE"] + "\n")
            sys.exit(254)
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
    aws_env: list[str]


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


def deploy_env(sandbox: Path) -> dict[str, str]:
    """The environment every run starts from. The tfvars file is one inside the sandbox, so the
    owner's real infra/live/terraform.tfvars (git-ignored, made at G5) never changes a test."""
    return {
        "PATH": str(sandbox / "bin"),
        "HOME": str(sandbox),
        "FAKE_LOG": str(sandbox / "calls.jsonl"),
        "STATE_BUCKET": "nursing-ai-state-example",
        "DEPLOY_TFVARS": str(sandbox / "no-such.tfvars"),
    }


def run_deploy(
    sandbox: Path, *args: str, approved: bool = True, extra: dict[str, str] | None = None
) -> Run:
    log = sandbox / "calls.jsonl"
    env = deploy_env(sandbox)
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
        ("s3", "cp"): "s3 cp index",
        ("cloudfront", "create-invalidation"): "invalidate",
        ("cloudwatch", "describe-alarms"): "check alarms",
    }
    if argv[:2] == ["lambda", "invoke"]:
        return f"invoke {json.loads(argv[argv.index('--payload') + 1])['task']}"
    if argv[:2] == ["s3", "sync"]:
        return f"s3 sync {argv[2]}"
    return names.get((argv[0], argv[1]))


def steps(run: Run) -> list[str]:
    return [s for c in run.calls if (s := label(c))]


NORMAL_DEMO = [
    "pnpm build",
    "terraform init",
    "docker build",
    "docker push",
    "point ops function",
    "invoke migrate",
    "terraform apply",
    "invoke seed-demo",
    "invoke smoke",
    "s3 sync web/dist/assets",
    "s3 sync web/dist",
    "s3 cp index",
    "invalidate",
    "check alarms",
]
FIRST_DEMO = [
    "pnpm build",
    "terraform init",
    "first-deploy check",
    "docker build",
    "docker push",
    "terraform apply",
    "invoke migrate",
    "invoke seed-demo",
    "invoke smoke",
    "s3 sync web/dist/assets",
    "s3 sync web/dist",
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
    variables = [apply_call[i + 1] for i, a in enumerate(apply_call) if a == "-var"]
    # The environment is also given on the command line: a tfvars file or TF_VAR_environment cannot
    # point the apply at another environment than the one typed.
    assert variables == [f"image_uri={tag}", "environment=demo"]
    assert "-lock-timeout=300s" in apply_call
    push = next(c.argv for c in run.calls if label(c) == "docker push")
    assert push[-1] == tag
    update = next(a for a in run.aws if a[:2] == ["lambda", "update-function-code"])
    assert update[update.index("--function-name") + 1] == "nursing-ai-demo-ops"
    assert update[update.index("--image-uri") + 1] == tag
    printed = [ln for ln in run.result.stdout.splitlines() if ln.startswith("deploy: ")]
    assert "deploy: migrate" in printed


# What `pnpm build` leaves in web/dist: Vite's output under assets/, named by content hash, and
# web/public's files under the names they have in the repo.
WEB_DIST = (
    "index.html",
    "assets/index-Bx3kT9aZ.js",
    "assets/index-Cq1vR7mP.css",
    "assets/StaffPage-D4hN2sLw.js",
    "fonts/AtkinsonHyperlegibleNext-latin.woff2",
    "fonts/AtkinsonHyperlegibleMono-latin.woff2",
    "fonts/OFL.txt",
    "mockServiceWorker.js",
)
A_YEAR = "public, max-age=31536000, immutable"
WEB_BUCKET = "s3://nursing-ai-demo-web"


def sync_takes(argv: list[str], path: str) -> bool:
    """Whether `aws s3 sync` uploads `path`, applying its filters the way the AWS CLI does.

    The CLI joins each `--exclude`/`--include` pattern to the source folder and matches it with
    fnmatch, whose `*` also crosses `/`; the last pattern that matches decides.
    """
    taken = True
    for flag, pattern in itertools.pairwise(argv):
        if flag in ("--exclude", "--include") and fnmatch.fnmatchcase(path, f"{argv[2]}/{pattern}"):
            taken = flag == "--include"
    return taken


def web_uploads(run: Run) -> dict[str, str]:
    """The bucket key and Cache-Control of each web/dist file the deploy uploads (the last wins)."""
    uploads: dict[str, str] = {}
    for argv in run.aws:
        if argv[:2] not in (["s3", "sync"], ["s3", "cp"]):
            continue
        source, target = argv[2], argv[3]
        cache_control = argv[argv.index("--cache-control") + 1]
        if argv[1] == "cp":
            uploads[target.removeprefix(f"{WEB_BUCKET}/")] = cache_control
            continue
        for name in WEB_DIST:
            path = f"web/dist/{name}"
            if path.startswith(f"{source}/") and sync_takes(argv, path):
                key = f"{target}/{path.removeprefix(f'{source}/')}"
                uploads[key.removeprefix(f"{WEB_BUCKET}/")] = cache_control
    return uploads


def test_deploy_caches_only_the_hashed_assets_for_a_year(sandbox: Path) -> None:
    # A file whose name stays the same from build to build (index.html, the fonts, their licence)
    # must be checked again after a deploy: a year's `immutable` would pin the old bytes in
    # browsers and in CloudFront, and the deploy invalidates only /index.html.
    run = run_deploy(sandbox, "demo")
    assert run.result.returncode == 0, run.result.stderr
    assert web_uploads(run) == {
        "index.html": "no-cache",
        "assets/index-Bx3kT9aZ.js": A_YEAR,
        "assets/index-Cq1vR7mP.css": A_YEAR,
        "assets/StaffPage-D4hN2sLw.js": A_YEAR,
        "fonts/AtkinsonHyperlegibleNext-latin.woff2": "no-cache",
        "fonts/AtkinsonHyperlegibleMono-latin.woff2": "no-cache",
        "fonts/OFL.txt": "no-cache",
    }
    syncs = [a for a in run.aws if a[:2] == ["s3", "sync"]]
    assert syncs, "the web app is never synced"
    # Old hashed files stay: a tab on the old build may still ask for a chunk it names (B-9).
    by_source = {a[2]: a for a in syncs}
    assert "--delete" not in by_source["web/dist/assets"]
    assert "--delete" in by_source["web/dist"]
    invalidation = next(a for a in run.aws if a[:2] == ["cloudfront", "create-invalidation"])
    assert invalidation[invalidation.index("--distribution-id") + 1] == "E123EXAMPLE"
    assert invalidation[invalidation.index("--paths") + 1] == "/index.html"


def test_deploy_never_uploads_the_mock_service_worker(sandbox: Path) -> None:
    # MSW's worker serves the in-browser mock API only; the live site has no use for it.
    run = run_deploy(sandbox, "demo")
    assert run.result.returncode == 0, run.result.stderr
    assert "mockServiceWorker.js" not in web_uploads(run)


def test_index_html_is_uploaded_after_every_asset(sandbox: Path) -> None:
    # A new index.html names the new build's assets; they must be in the bucket first.
    run = run_deploy(sandbox, "demo")
    order = [s for s in steps(run) if s.startswith("s3 ")]
    assert order[-1] == "s3 cp index"


def test_first_deploy_applies_before_it_migrates(sandbox: Path) -> None:
    run = run_deploy(sandbox, "demo", extra={"FAKE_FIRST_DEPLOY": "1"})
    assert run.result.returncode == 0, run.result.stderr
    assert steps(run) == FIRST_DEMO


def test_the_apply_first_override_applies_before_it_migrates_on_a_normal_run(
    sandbox: Path,
) -> None:
    run = run_deploy(sandbox, "demo", extra={"DEPLOY_APPLY_FIRST": "yes"})
    assert run.result.returncode == 0, run.result.stderr
    assert steps(run) == [step for step in FIRST_DEMO if step != "first-deploy check"]


def test_the_apply_first_override_still_needs_approval(sandbox: Path) -> None:
    run = run_deploy(sandbox, "demo", approved=False, extra={"DEPLOY_APPLY_FIRST": "yes"})
    assert run.result.returncode != 0
    assert steps(run) == []


def test_the_apply_first_override_still_refuses_another_environments_state(
    sandbox: Path,
) -> None:
    run = run_deploy(sandbox, "demo", extra={"DEPLOY_APPLY_FIRST": "yes", "FAKE_STATE_ENV": "prod"})
    assert run.result.returncode != 0
    assert steps(run) == ["pnpm build", "terraform init"]


def test_state_without_the_ops_function_and_a_live_function_is_not_a_first_deploy(
    sandbox: Path,
) -> None:
    # A first deploy whose apply failed part-way: resources in the state, no outputs yet.
    run = run_deploy(sandbox, "demo", extra={"FAKE_NO_STATE": "1", "FAKE_STATE_RESOURCES": "1"})
    assert run.result.returncode == 0, run.result.stderr
    assert steps(run) == ["pnpm build", "terraform init", "first-deploy check", *NORMAL_DEMO[2:]]


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
    assert steps(run) == ["pnpm build", "terraform init", "first-deploy check"]


ACCOUNT = "210987654321"
ARN = f"arn:aws:sts::{ACCOUNT}:assumed-role/deploy-role/session"


@pytest.mark.parametrize(
    ("message", "shown"),
    [
        (
            f"An error occurred (AccessDeniedException) when calling the GetFunction "
            f"operation: User: {ARN} is not authorized to perform: lambda:GetFunction",
            "AccessDeniedException",
        ),
        (f"Unable to locate credentials for {ARN}", "unknown AWS error"),
    ],
)
def test_an_aws_error_shows_its_code_but_never_the_account_id_or_arn(
    sandbox: Path, message: str, shown: str
) -> None:
    extra = {"FAKE_NO_STATE": "1", "FAKE_GET_FUNCTION_MESSAGE": message}
    run = run_deploy(sandbox, "demo", extra=extra)
    assert run.result.returncode != 0
    assert shown in run.result.stderr
    everything = run.result.stdout + run.result.stderr
    assert ACCOUNT not in everything
    assert ARN not in everything
    assert steps(run) == ["pnpm build", "terraform init", "first-deploy check"]


def test_state_of_another_environment_stops_before_the_build(sandbox: Path) -> None:
    run = run_deploy(sandbox, "demo", extra={"FAKE_STATE_ENV": "prod"})
    assert run.result.returncode != 0
    assert "nursing-ai-prod-ops" in run.result.stderr
    assert steps(run) == ["pnpm build", "terraform init"]


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


def test_the_web_app_is_built_first_and_sees_no_aws_variable(sandbox: Path) -> None:
    # A broken build stops the deploy before anything changes, and build-time code from an npm
    # dependency never sees the sign-in (B-3): neither the AWS credentials nor, in CI, GitHub's
    # OIDC request variables, with which it could ask for a token the deploy role trusts.
    credentials = {
        "AWS_ACCESS_KEY_ID": "AKIAEXAMPLE",
        "AWS_SECRET_ACCESS_KEY": "stand-in",
        "AWS_SESSION_TOKEN": "stand-in",
        "AWS_PROFILE": "nursing-ai",
        "AWS_REGION": "ap-southeast-2",
        "ACTIONS_ID_TOKEN_REQUEST_URL": "https://token.example.com/",
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "stand-in",
    }
    run = run_deploy(sandbox, "demo", extra=credentials)
    assert run.result.returncode == 0, run.result.stderr
    assert steps(run)[0] == "pnpm build"
    build = next(c for c in run.calls if c.tool == "pnpm")
    assert build.aws_env == []
    # The other tools still get them.
    assert "AWS_ACCESS_KEY_ID" in next(c for c in run.calls if c.tool == "aws").aws_env


def test_a_failing_web_build_stops_the_deploy_before_anything_else_runs(sandbox: Path) -> None:
    run = run_deploy(sandbox, "demo", extra={"FAKE_PNPM_FAILS": "1"})
    assert run.result.returncode != 0
    assert steps(run) == ["pnpm build"]


def test_the_apply_waits_up_to_five_minutes_for_the_state_lock(sandbox: Path) -> None:
    run = run_deploy(sandbox, "demo")
    apply_call = next(c.argv for c in run.calls if label(c) == "terraform apply")
    assert "-lock-timeout=300s" in apply_call


def test_the_default_tfvars_is_inside_the_sandbox(sandbox: Path) -> None:
    assert Path(deploy_env(sandbox)["DEPLOY_TFVARS"]).is_relative_to(sandbox)


def test_a_tfvars_that_sets_the_database_password_version_is_refused(sandbox: Path) -> None:
    # CI cannot see the owner's tfvars, so its next deploy would lower the value and rotate the
    # password (B-11).
    tfvars = sandbox / "terraform.tfvars"
    tfvars.write_text('environment = "demo"\ndatabase_password_version = 2\n')
    run = run_deploy(sandbox, "demo", extra={"DEPLOY_TFVARS": str(tfvars)})
    assert run.result.returncode != 0
    assert "database_password_version" in run.result.stderr
    assert run.calls == []
    tfvars.write_text("# database_password_version = 2\nai_monthly_cap_usd = 5\n")
    ok = run_deploy(sandbox, "demo", extra={"DEPLOY_TFVARS": str(tfvars)})
    assert ok.result.returncode == 0, ok.result.stderr


def test_a_state_that_cannot_be_listed_stops_the_deploy(sandbox: Path) -> None:
    # An unreadable state must not be taken for an empty one (CL8).
    extra = {"FAKE_NO_STATE": "1", "FAKE_STATE_LIST_FAILS": "1"}
    run = run_deploy(sandbox, "demo", extra=extra)
    assert run.result.returncode != 0
    assert "state" in run.result.stderr
    assert steps(run) == ["pnpm build", "terraform init"]


def test_an_empty_state_with_a_live_ops_function_is_refused(sandbox: Path) -> None:
    # Wrong bucket or wiped state: an apply would try to create what already exists.
    run = run_deploy(sandbox, "demo", extra={"FAKE_NO_STATE": "1"})
    assert run.result.returncode != 0
    assert "state" in run.result.stderr
    assert steps(run) == ["pnpm build", "terraform init", "first-deploy check"]


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


AWS_FAILURE_PATHS = [
    "ecr describe-repositories",
    "ecr get-login-password",
    "lambda update-function-code",
    "lambda wait",
    "lambda invoke",
    "s3 sync",
    "s3 cp",
    "cloudfront create-invalidation",
    "cloudwatch describe-alarms",
]
RAW_AWS_ERROR = (
    f"An error occurred (AccessDenied) when calling the Operation: User: {ARN} is not "
    f"authorized, account {ACCOUNT}, registry {REGISTRY}"
)


@pytest.mark.parametrize("path", AWS_FAILURE_PATHS)
@pytest.mark.parametrize(
    ("message", "shown"),
    [
        (RAW_AWS_ERROR, "AccessDenied"),
        (f"Unable to locate credentials for {ARN}", "unknown AWS error"),
    ],
)
def test_every_aws_call_that_fails_shows_only_its_error_code(
    sandbox: Path, path: str, message: str, shown: str
) -> None:
    extra = {"FAKE_AWS_FAIL": path, "FAKE_FAIL_MESSAGE": message}
    run = run_deploy(sandbox, "demo", extra=extra)
    assert run.result.returncode != 0
    everything = run.result.stdout + run.result.stderr
    assert shown in run.result.stderr
    for secret in (ACCOUNT, ARN, REGISTRY):
        assert secret not in everything
    assert "Unable to locate" not in everything


@pytest.mark.parametrize(
    ("extra", "step"),
    [
        ({"FAKE_DOCKER_FAIL": "build"}, "docker build"),
        ({"FAKE_DOCKER_FAIL": "push"}, "docker push"),
        ({"FAKE_DOCKER_FAIL": "login"}, "docker login"),
        ({"FAKE_INIT_FAILS": "1"}, "terraform init"),
        ({"FAKE_APPLY_PRINTS": "1", "FAKE_APPLY_FAILS": "1"}, "terraform apply"),
    ],
)
def test_docker_and_terraform_failures_hide_account_ids(
    sandbox: Path, extra: dict[str, str], step: str
) -> None:
    extra = {**extra, "FAKE_FAIL_MESSAGE": f"failed for {ARN} at {REGISTRY}"}
    run = run_deploy(sandbox, "demo", extra=extra)
    assert run.result.returncode != 0
    everything = run.result.stdout + run.result.stderr
    assert ACCOUNT not in everything
    assert step.split()[0] in everything


def test_what_terraform_apply_prints_never_shows_an_account_id(sandbox: Path) -> None:
    extra = {"FAKE_APPLY_PRINTS": "1", "FAKE_FAIL_MESSAGE": f'  + arn = "{ARN}"'}
    run = run_deploy(sandbox, "demo", extra=extra)
    assert run.result.returncode == 0, run.result.stderr
    assert "deploy: done" in run.result.stdout
    assert ACCOUNT not in run.result.stdout + run.result.stderr
    assert "deploy-role/session" in run.result.stdout
