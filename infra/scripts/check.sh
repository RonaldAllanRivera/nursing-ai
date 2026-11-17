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
unset AWS_PROFILE AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_DEFAULT_PROFILE
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
  # Show validate's output only when it fails or warns, and test's only on failure.
  out="$(terraform -chdir="$dir" validate 2>&1)" \
    || { echo "$out" >&2; echo "failed: validate in $dir" >&2; exit 1; }
  case "$out" in *Warning*) echo "$out" ;; esac
  if [ -d "$dir/tests" ]; then
    out="$(terraform -chdir="$dir" test 2>&1)" \
      || { echo "$out" >&2; echo "failed: test in $dir" >&2; exit 1; }
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
    # Braces are counted on a copy of the line without strings and comments.
    # A plain `value` is allowed only on a parameter whose type is "String"
    # (a public setting such as the site address). It is reported when the
    # resource ends, because `type` may come after it.
    awk -v file="$f" '
      /^[[:space:]]*resource[[:space:]]+"aws_ssm_parameter"/ { inside = 1; depth = 0; plain = ""; is_string = 0 }
      inside {
        l = $0
        if (l ~ /^[[:space:]]*type[[:space:]]*=[[:space:]]*"String"[[:space:]]*$/) is_string = 1
        gsub(/"([^"\\]|\\.)*"/, "", l)
        sub(/(#|\/\/).*/, "", l)
        if (l ~ /^[[:space:]]*value[[:space:]]*=/ && plain == "") plain = FNR
        n = gsub(/\{/, "{", l); m = gsub(/\}/, "}", l)
        depth += n - m
        if (depth <= 0 && (n > 0 || m > 0)) {
          inside = 0
          if (plain != "" && !is_string) {
            print file ":" plain ": plaintext value in aws_ssm_parameter"; found = 1
          }
        }
      }
      END { exit found }
    ' "$f" || bad=1
  done
fi
[ "$bad" -eq 0 ] || exit 1

# 8. Done.
echo "infra check: ok"
