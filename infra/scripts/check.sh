#!/usr/bin/env bash
# One gate for the Terraform in infra/: format, validate, test, lint, scan and
# two static checks. Run it from anywhere; it prints one line per folder.
set -euo pipefail
shopt -s nullglob

# 1. Work from infra/, use the pinned tools and a shared provider cache.
repo_root="$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." >/dev/null && pwd)"
cd "$repo_root/infra"
export PATH="$repo_root/.tools/bin:$PATH"
export TF_PLUGIN_CACHE_DIR="${TF_PLUGIN_CACHE_DIR:-$HOME/.terraform.d/plugin-cache}"
mkdir -p "$TF_PLUGIN_CACHE_DIR"

# The checks never need AWS. Hide every credential and config so a test that
# forgot its mock provider fails instead of signing in to a real account.
unset AWS_PROFILE AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_DEFAULT_PROFILE \
  AWS_SECURITY_TOKEN AWS_WEB_IDENTITY_TOKEN_FILE AWS_ROLE_ARN AWS_ROLE_SESSION_NAME \
  AWS_CONTAINER_CREDENTIALS_FULL_URI AWS_CONTAINER_CREDENTIALS_RELATIVE_URI \
  AWS_CONTAINER_AUTHORIZATION_TOKEN AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE
export AWS_CONFIG_FILE=/dev/null AWS_SHARED_CREDENTIALS_FILE=/dev/null AWS_EC2_METADATA_DISABLED=true

# 2. Formatting.
terraform fmt -check -recursive

# 3. Init (no backend), validate and test every root and module.
for dir in bootstrap live modules/*; do
  [ -f "$dir/versions.tf" ] || continue
  init_args=(-backend=false -input=false)
  [ -f "$dir/.terraform.lock.hcl" ] && init_args+=(-lockfile=readonly)
  terraform -chdir="$dir" init "${init_args[@]}" >/dev/null \
    || { echo "failed: init in $dir" >&2; exit 1; }
  # Show validate's and test's output when it fails or warns.
  out="$(terraform -chdir="$dir" validate 2>&1)" \
    || { echo "$out" >&2; echo "failed: validate in $dir" >&2; exit 1; }
  case "$out" in *Warning*) echo "$out" ;; esac
  if [ -d "$dir/tests" ]; then
    out="$(terraform -chdir="$dir" test 2>&1)" \
      || { echo "$out" >&2; echo "failed: test in $dir" >&2; exit 1; }
    case "$out" in *Warning*) echo "$out" ;; esac
    echo "ok: $dir (validate, test)"
  else
    echo "ok: $dir (validate)"
  fi
done

# 4. Lint with the AWS ruleset (the plugin is downloaded on first use).
if ! tflint --init --config="$PWD/.tflint.hcl" >/dev/null; then
  sleep 5
  tflint --init --config="$PWD/.tflint.hcl" >/dev/null
fi
tflint --recursive --config="$PWD/.tflint.hcl"

# 5. Security scan: HIGH and CRITICAL findings fail the check.
if ! trivy_out="$(trivy config --quiet --severity HIGH,CRITICAL --exit-code 1 . 2>&1)"; then
  echo "$trivy_out" >&2
  exit 1
fi

# All *.tf files, without any .terraform/ download folder. A failing find
# stops the script (it is not hidden inside a process substitution).
tf_list="$(find . -name .terraform -prune -o -name '*.tf' -type f -print)"
tf_files=()
[ -z "$tf_list" ] || mapfile -t tf_files <<<"$tf_list"

# 6. Forbidden resources: no NAT, no internet gateway, no Elastic IP
#    (outbound traffic is IPv6 only). Only lines that start a resource count.
bad=0
if [ ${#tf_files[@]} -gt 0 ]; then
  for type in aws_nat_gateway aws_internet_gateway aws_eip; do
    rc=0
    grep -lE "^[[:space:]]*resource[[:space:]]+\"$type\"" "${tf_files[@]}" || rc=$?
    [ "$rc" -le 1 ] || exit 2
    if [ "$rc" -eq 0 ]; then
      echo "forbidden resource $type declared in the file(s) above" >&2
      bad=1
    fi
  done
fi
[ "$bad" -eq 0 ] || exit 1

# 7. No plaintext secrets: only write-only arguments (master_password_wo,
#    value_wo) may carry them. Print file and line, never the value.
if [ ${#tf_files[@]} -gt 0 ]; then
  rc=0
  hits="$(grep -nHE '^[[:space:]]*(master_password|insecure_value)[[:space:]]*=' "${tf_files[@]}")" || rc=$?
  [ "$rc" -le 1 ] || exit 2
  if [ "$rc" -eq 0 ]; then
    echo "$hits" | cut -d: -f1,2 | sed 's/$/: plaintext secret argument/'
    bad=1
  fi
  for f in "${tf_files[@]}"; do
    # The scan, and why it reads HCL the way it does, are in ssm-plaintext.awk.
    awk -v file="$f" -f "$repo_root/infra/scripts/ssm-plaintext.awk" "$f" || bad=1
  done
fi
[ "$bad" -eq 0 ] || exit 1

# 8. Done.
echo "infra check: ok"
