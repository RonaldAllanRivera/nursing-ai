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
    # Each line is first cleaned by scan(): comments (# and //, and /* */ over
    # one or many lines) and heredoc bodies are removed, so none of them can
    # hide a `value`, fake a `type`, or open a fake resource. It makes two
    # copies: `keep` (strings intact, to read type = "String") and `blank`
    # (strings emptied, to count braces and find `value`). A plain `value` is
    # allowed only on a parameter whose type is "String" (a public setting such
    # as the site address). It counts only at the resource's own level (so a
    # one-line `{ value = "x" }` is caught and a tag called value is not), and
    # it is reported when the resource ends, because `type` may come after it.
    # A file the scan cannot follow to its end (an open heredoc, comment,
    # string, interpolation or resource, or unbalanced braces) is a failure,
    # never a silent pass.
    awk -v file="$f" '
      # Strings and ${ } interpolations nest, and an interpolation may run over
      # several lines, so the state lives in a stack (stk, sp) kept across lines:
      # "S" is a string, "I" an interpolation (cnt[sp] counts its own braces).
      # Inside a string only the three characters $${ and %%{ are literal (so
      # "$$${" is a literal $ and then an interpolation). Comments and heredocs
      # are recognised wherever the top of the stack is not a string, so also
      # inside ${ }, where their quotes and braces must not move the stack.
      function scan(line,    i, n, c, c2, c3, top, rest) {
        keep = ""; blank = ""
        n = length(line)
        for (i = 1; i <= n; i++) {
          c = substr(line, i, 1); c2 = substr(line, i, 2)
          if (in_block) {                                  # inside /* ... */
            if (c2 == "*/") { in_block = 0; i++ }
            continue
          }
          top = (sp > 0) ? stk[sp] : "C"
          if (top == "S") {                                # inside "..."
            if (c == "\\") { keep = keep c substr(line, i + 1, 1); i++; continue }
            c3 = substr(line, i, 3)                        # only the three characters $${ and %%{ are literal
            if (c3 == "$${" || c3 == "%%{") { keep = keep c3; i += 2; continue }
            if (c2 == "${" || c2 == "%{") { sp++; stk[sp] = "I"; cnt[sp] = 0; keep = keep c2; i++; continue }
            keep = keep c
            if (c == "\"") { sp--; if (sp == 0) blank = blank c }
            continue
          }
          {                                                # code: the top level or inside ${ }
            if (c == "#" || c2 == "//") break              # trailing comment
            if (c2 == "/*") { in_block = 1; i++; continue }
            if (c2 == "<<") {                              # heredoc: body starts next line
              rest = substr(line, i + 2)
              if (match(rest, /^-?[A-Za-z_][A-Za-z0-9_-]*/)) {
                heredoc = substr(rest, 1, RLENGTH); sub(/^-/, "", heredoc)
                keep = keep c2; if (sp == 0) blank = blank c2
                i += 1 + RLENGTH
                continue
              }
            }
          }
          if (sp > 0) {                                    # inside ${ }: its own braces are counted
            if (c == "{") cnt[sp]++
            if (c == "}") { if (cnt[sp] == 0) { sp--; keep = keep c; continue } else cnt[sp]-- }
          }
          if (c == "\"") { sp++; stk[sp] = "S"; keep = keep c; if (sp == 1) blank = blank c; continue }
          keep = keep c
          if (sp == 0) blank = blank c
        }
        # No valid HCL string spans lines (an interpolation may): a string still
        # open at the line end means the scan lost track, so it is reported at
        # the end, then dropped so one bad line does not hide the rest.
        while (sp > 0 && stk[sp] == "S") { lost = 1; sp-- }
      }
      {
        sub(/\r$/, "")                                     # CRLF files
        if (heredoc != "") {                               # a heredoc body: ignore it
          t = $0; gsub(/^[ \t]+|[ \t]+$/, "", t)
          if (t == heredoc) heredoc = ""
          next
        }
        scan($0)
        if (keep ~ /^[ \t]*resource[ \t]+"aws_ssm_parameter"/) {
          inside = 1; opened = 0; depth = 0; plain = ""; is_string = 0
        }
        if (inside && depth == 1 && keep ~ /^[ \t]*type[ \t]*=[ \t]*"String"[ \t]*$/) is_string = 1
        for (i = 1; i <= length(blank); i++) {
          c = substr(blank, i, 1)
          if (c == "{") { gdepth++; if (inside) { depth++; opened = 1 } }
          else if (c == "}") { gdepth--; if (inside) depth-- }
          else if (inside && depth == 1 && plain == "" && substr(blank, i) ~ /^value[ \t]*=([^=]|$)/ \
                   && (i == 1 || substr(blank, i - 1, 1) !~ /[A-Za-z0-9_-]/)) plain = FNR
        }
        if (inside && opened && depth <= 0) {
          inside = 0
          if (plain != "" && !is_string) {
            print file ":" plain ": plaintext value in aws_ssm_parameter"; found = 1
          }
        }
      }
      # Fail closed: a heredoc, comment, string, interpolation or resource still
      # open at the end, or braces that do not balance, means the scan lost track.
      END {
        if (lost || heredoc != "" || in_block || sp > 0 || inside || gdepth != 0) {
          print file ": could not parse to the end (open heredoc, comment, string or resource, or unbalanced braces)"
          found = 1
        }
        exit found
      }
    ' "$f" || bad=1
  done
fi
[ "$bad" -eq 0 ] || exit 1

# 8. Done.
echo "infra check: ok"
