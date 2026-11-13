#!/usr/bin/env bash
# One gate for the Terraform in infra/: format, validate, test, lint, scan and
# two static checks. Run it from anywhere; it prints one line per folder.
set -euo pipefail
shopt -s nullglob

# 1. Work from infra/, use the pinned tools and a shared provider cache.
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root/infra"
export PATH="$repo_root/.tools/bin:$PATH"
export TF_PLUGIN_CACHE_DIR="${TF_PLUGIN_CACHE_DIR:-$HOME/.terraform.d/plugin-cache}"
mkdir -p "$TF_PLUGIN_CACHE_DIR"

# 2. Formatting.
terraform fmt -check -recursive

# 3. Init (no backend), validate and test every root and module.
for dir in bootstrap live modules/*; do
  [ -f "$dir/versions.tf" ] || continue
  init_args=(-backend=false -input=false)
  [ -f "$dir/.terraform.lock.hcl" ] && init_args+=(-lockfile=readonly)
  terraform -chdir="$dir" init "${init_args[@]}" >/dev/null
  terraform -chdir="$dir" validate >/dev/null
  if [ -d "$dir/tests" ]; then
    terraform -chdir="$dir" test >/dev/null
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

# All *.tf files, without any .terraform/ download folder.
tf_files=()
while IFS= read -r -d '' f; do tf_files+=("$f"); done \
  < <(find . -name .terraform -prune -o -name '*.tf' -type f -print0)

# 6. Forbidden resources: no NAT, no internet gateway, no Elastic IP
#    (outbound traffic is IPv6 only).
bad=0
if [ ${#tf_files[@]} -gt 0 ]; then
  for type in aws_nat_gateway aws_internet_gateway aws_eip; do
    if grep -lE "resource[[:space:]]+\"$type\"" "${tf_files[@]}"; then
      echo "forbidden resource $type declared in the file(s) above" >&2
      bad=1
    fi
  done
fi
[ "$bad" -eq 0 ] || exit 1

# 7. No plaintext secrets: only write-only arguments (master_password_wo,
#    value_wo) may carry them. Print file and line, never the value.
if [ ${#tf_files[@]} -gt 0 ]; then
  if grep -nHE '^[[:space:]]*(master_password|insecure_value)[[:space:]]*=' "${tf_files[@]}" \
      | cut -d: -f1,2 | sed 's/$/: plaintext secret argument/' | grep .; then
    bad=1
  fi
  for f in "${tf_files[@]}"; do
    awk -v file="$f" '
      /resource[[:space:]]+"aws_ssm_parameter"/ { inside = 1; depth = 0 }
      inside {
        if ($0 ~ /^[[:space:]]*value[[:space:]]*=/) {
          print file ":" FNR ": plaintext value in aws_ssm_parameter"; found = 1
        }
        n = gsub(/\{/, "{"); m = gsub(/\}/, "}")
        depth += n - m
        if (depth <= 0 && (n > 0 || m > 0)) inside = 0
      }
      END { exit found }
    ' "$f" || bad=1
  done
fi
[ "$bad" -eq 0 ] || exit 1

# 8. Done.
echo "infra check: ok"
