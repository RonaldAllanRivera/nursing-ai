#!/usr/bin/env bash
# Deploys the whole stack for one environment: builds the image once and pushes it to ECR, points
# the ops function at it, migrates, applies infra/live with that image, seeds the demo (demo only),
# smoke-tests, uploads the web app and checks the alarms.
#
#   scripts/deploy.sh demo|prod
#
# Needs:
#   DEPLOY_APPROVED=yes  nothing runs without it (no build, no push, no apply).
#   STATE_BUCKET         the Terraform state bucket (the `state_bucket_name` output of bootstrap).
#   AWS sign-in          a signed-in profile (AWS_PROFILE, from `aws login`) or, in CI, the role the
#                        OIDC step assumed. When AWS_PROFILE is set it is also given to Terraform.
#   TF_VAR_*             every Terraform variable but `image_uri` (for example TF_VAR_alert_email and
#                        TF_VAR_domain_name), or the git-ignored infra/live/terraform.tfvars. The
#                        script sets TF_VAR_environment itself; a tfvars file that sets `environment`
#                        to another name is refused (DEPLOY_TFVARS names a different tfvars file).
#   docker, terraform, pnpm, python3, git and the AWS CLI on PATH.
#
# It never reads a secret: no SSM parameter, no Secrets Manager, no --with-decryption.
# CI logs of this public repository are public: the script prints the image tag but not the registry
# host (it carries the account id), and the workflow must not echo environment variables or plans
# beyond what the script prints.
#
# Called the same way from both places:
#   `make deploy` (the owner's PC) asks for the environment's name, then runs
#     DEPLOY_APPROVED=yes scripts/deploy.sh <name>
#   `.github/workflows/deploy.yml` runs the same line after the `production` environment's reviewer
#     approves, as the OIDC deploy role.
#
# The first deploy (no ops function yet) applies before it migrates, since the apply makes the ops
# function. The first apply is slow: the functions wait for the CloudFront distribution.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF=(terraform -chdir=infra/live)
WORK=""
ENVIRONMENT=""
OPS_FUNCTION=""
FIRST_DEPLOY=""
IMAGE_URI=""
IMAGE_TAG=""
REGISTRY=""

say() { printf 'deploy: %s\n' "$*"; }
die() { printf 'deploy: %s\n' "$*" >&2; exit 1; }
cleanup() { [[ -n "$WORK" ]] && rm -rf "$WORK"; return 0; }

check_arguments() {
  if [[ $# -ne 1 || ( "$1" != "demo" && "$1" != "prod" ) ]]; then
    printf 'usage: scripts/deploy.sh demo|prod\n' >&2
    exit 2
  fi
  ENVIRONMENT="$1"
  OPS_FUNCTION="nursing-ai-${ENVIRONMENT}-ops"
}

check_approval() {
  [[ "${DEPLOY_APPROVED:-}" == "yes" ]] \
    || die "set DEPLOY_APPROVED=yes to deploy; nothing was run"
  [[ -n "${STATE_BUCKET:-}" ]] || die "set STATE_BUCKET to the Terraform state bucket; nothing was run"
}

terraform_init() {
  say "terraform init"
  export TF_VAR_environment="$ENVIRONMENT"
  local backend=(-backend-config="bucket=${STATE_BUCKET}")
  if [[ -n "${AWS_PROFILE:-}" ]]; then
    backend+=(-backend-config="profile=${AWS_PROFILE}")
    export TF_VAR_aws_profile="$AWS_PROFILE"
  fi
  "${TF[@]}" init -input=false "${backend[@]}" >/dev/null
}

# A simple grep, not an HCL parse: the tfvars file beats TF_VAR_environment, so a different name in
# it would apply to another environment than the one typed on the command line.
check_tfvars_environment() {
  local file="${DEPLOY_TFVARS:-infra/live/terraform.tfvars}" named=""
  [[ -f "$file" ]] || return 0
  named="$(sed -n 's/^[[:space:]]*environment[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' "$file" | tail -n 1)"
  if [[ -n "$named" && "$named" != "$ENVIRONMENT" ]]; then
    die "the tfvars file sets environment to \"${named}\", not \"${ENVIRONMENT}\"; nothing was built"
  fi
}

# Decides whether this is the first deploy from two signals that must agree: the state has no ops
# function output AND Lambda says the function does not exist. A state that names the ops function
# of another environment is refused before anything is built.
check_first_deploy() {
  say "check the state and the ops function"
  local named="" error_file="$WORK/get-function.err"
  named="$("${TF[@]}" output -raw ops_function_name 2>/dev/null || true)"
  if [[ -n "$named" ]]; then
    [[ "$named" == "$OPS_FUNCTION" ]] \
      || die "the state belongs to ${named}, not ${OPS_FUNCTION}; nothing was built"
    FIRST_DEPLOY=""
    return 0
  fi
  if aws lambda get-function --function-name "$OPS_FUNCTION" >/dev/null 2>"$error_file"; then
    FIRST_DEPLOY=""
  elif grep -q 'ResourceNotFoundException' "$error_file"; then
    FIRST_DEPLOY="yes"
    say "first deploy: the apply runs before the migration"
  else
    # An AWS CLI error names the function and the error code, never a secret.
    cat "$error_file" >&2
    die "could not tell whether the ops function exists; nothing was built"
  fi
}

image_tag() {
  printf '%s-%s' "$(git -C "$ROOT" rev-parse --short=12 HEAD)" "$(date -u +%Y%m%d%H%M%S)"
}

build_and_push_image() {
  say "build and push the image"
  REGISTRY="$(aws ecr describe-repositories --repository-names nursing-ai \
    --query 'repositories[0].repositoryUri' --output text)"
  [[ -n "$REGISTRY" && "$REGISTRY" != "None" ]] || die "the nursing-ai registry was not found"
  IMAGE_TAG="$(image_tag)"
  IMAGE_URI="${REGISTRY}:${IMAGE_TAG}"
  say "image tag ${IMAGE_TAG}"
  aws ecr get-login-password | docker login --username AWS --password-stdin "${REGISTRY%%/*}" >/dev/null
  docker build --quiet --platform linux/amd64 --provenance=false -f api/Dockerfile -t "$IMAGE_URI" . >/dev/null
  docker push --quiet "$IMAGE_URI" >/dev/null
}

point_ops_function() {
  say "point the ops function at the new image"
  aws lambda update-function-code --function-name "$OPS_FUNCTION" --image-uri "$IMAGE_URI" >/dev/null
  aws lambda wait function-updated --function-name "$OPS_FUNCTION"
}

# Invokes one ops task and stops the deploy unless its answer says ok.
run_ops_task() {
  local task="$1" answer="$WORK/$1.json"
  say "$task"
  aws lambda invoke --cli-read-timeout 900 --function-name "$OPS_FUNCTION" \
    --cli-binary-format raw-in-base64-out --payload "{\"task\":\"${task}\"}" "$answer" >/dev/null \
    || die "$task: the ops function could not be invoked"
  python3 - "$answer" "$task" <<'PY' || exit 1
import json, sys

path, task = sys.argv[1:]
try:
    with open(path) as handle:
        answer = json.load(handle)
except (OSError, ValueError):
    answer = None
if not isinstance(answer, dict) or answer.get("ok") is not True:
    failed = answer.get("failed") if isinstance(answer, dict) else None
    names = ", ".join(str(n) for n in failed) if isinstance(failed, list) else "no answer"
    print(f"deploy: {task} failed ({names})", file=sys.stderr)
    sys.exit(1)
PY
}

terraform_apply() {
  say "terraform apply"
  "${TF[@]}" apply -input=false -auto-approve -var "image_uri=${IMAGE_URI}"
}

tf_output() { "${TF[@]}" output -raw "$1"; }

check_ops_name() {
  [[ "$(tf_output ops_function_name)" == "$OPS_FUNCTION" ]] \
    || die "the ops_function_name output is not ${OPS_FUNCTION}"
}

build_web() {
  say "build the web app"
  pnpm -C web build
}

upload_web() {
  local bucket distribution
  bucket="$(tf_output web_bucket_name)"
  distribution="$(tf_output distribution_id)"
  say "upload the web app"
  aws s3 sync web/dist "s3://${bucket}" --delete --exclude index.html \
    --cache-control "public, max-age=31536000, immutable"
  aws s3 cp web/dist/index.html "s3://${bucket}/index.html" --cache-control "no-cache"
  aws cloudfront create-invalidation --distribution-id "$distribution" --paths /index.html >/dev/null
}

check_alarms() {
  say "check the alarms"
  "${TF[@]}" output -json alarm_names >"$WORK/alarm_names.json"
  local names
  names="$(python3 -c 'import json,sys; print(*json.load(open(sys.argv[1])).values())' "$WORK/alarm_names.json")"
  # shellcheck disable=SC2086  # the names are three words without spaces
  aws cloudwatch describe-alarms --alarm-names $names --output json >"$WORK/alarms.json"
  python3 - "$WORK/alarms.json" "$(tf_output http_api_id)" "$(tf_output dlq_name)" "$names" <<'PY' \
    || exit 1
import json, sys

path, api_id, dlq, names = sys.argv[1:]
with open(path) as handle:
    alarms = {a["AlarmName"]: a for a in json.load(handle).get("MetricAlarms", [])}
problems = []
for name in names.split():
    alarm = alarms.get(name)
    if alarm is None:
        problems.append(f"{name} was not found")
        continue
    state = alarm.get("StateValue")
    dims = {d["Name"]: d["Value"] for d in alarm.get("Dimensions", [])}
    if state == "ALARM":
        problems.append(f"{name} is in ALARM")
    elif state == "INSUFFICIENT_DATA":
        print(f"deploy: warning: {name} has no data yet")
    if name.endswith("-api-5xx") and dims.get("ApiId") != api_id:
        problems.append(f"{name} is not watching this API")
    if name.endswith("-dead-jobs") and dims.get("QueueName") != dlq:
        problems.append(f"{name} is not watching the dead-letter queue")
for problem in problems:
    print(f"deploy: {problem}", file=sys.stderr)
sys.exit(1 if problems else 0)
PY
}

main() {
  check_arguments "$@"
  check_approval
  cd "$ROOT"
  WORK="$(mktemp -d)"
  trap cleanup EXIT
  check_tfvars_environment
  terraform_init
  check_first_deploy
  build_and_push_image
  if [[ -n "$FIRST_DEPLOY" ]]; then
    terraform_apply
    run_ops_task migrate
  else
    point_ops_function
    run_ops_task migrate
    terraform_apply
  fi
  check_ops_name
  if [[ "$ENVIRONMENT" == "demo" ]]; then
    run_ops_task seed-demo
  fi
  run_ops_task smoke
  build_web
  upload_web
  check_alarms
  say "done: ${IMAGE_TAG}"
}

main "$@"
