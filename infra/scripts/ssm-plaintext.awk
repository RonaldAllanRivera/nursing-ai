# Step 7 of check.sh: no plaintext secret in an aws_ssm_parameter. Run once per file:
#   awk -v file=<path> -f ssm-plaintext.awk <path>
# Exit 0: clean. Exit 1: a finding, printed as "<file>:<line>: ...", never the value.
#
# Each line is first cleaned by scan(): comments (# and //, and /* */ over one or many lines) and
# heredoc bodies are removed, so none of them can hide a `value`, fake a `type`, or open a fake
# resource. It makes two copies: `keep` (strings intact, to read type = "String") and `blank`
# (strings emptied, to count braces and find `value`). A plain `value` is allowed only on a
# parameter whose type is "String" (a public setting such as the site address). It counts only at
# the resource's own level (so a one-line `{ value = "x" }` is caught and a tag called value is
# not), and it is reported when the resource ends, because `type` may come after it. A file the
# scan cannot follow to its end (an open heredoc, comment, string, interpolation or resource, or
# unbalanced braces) is a failure, never a silent pass.
#
# tests/repo/test_infra_secret_scan.py runs it on files written to fool it, under every awk found.

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
