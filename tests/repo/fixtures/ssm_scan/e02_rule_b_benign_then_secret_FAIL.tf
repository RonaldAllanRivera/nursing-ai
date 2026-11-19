locals {
  q1 = "say \"hi\""
  q2 = "a\\"
  q3 = "\\\""
  q4 = "\\\\"
  q5 = "\""
  q6 = "cost $"
  q7 = "100%"
  q8 = "$$"
  q9 = "%%"
  qa = "$$$${x}"
  qb = "%%%%{x}"
  qc = "héllo \"wörld\" it's"
  qd = "héllo \"wörld\" it's"
  qe = "a */ b /* c // d # e"
  qf = "${"\""}/x"
  qg = "${"}"}/x${"{"}"
  qh = "%{if true}\"%{endif}/x"
  qi = "${~"a"~}/x"
  h1 = <<EOT
"one quote
${"two"} quotes " and a } and { and /* and #
EOT
  h2 = <<-EOT
    "indented quote
    EOT
  h3 = "${trimspace(<<EOT
"
  a "quote" { in a heredoc inside an interpolation
EOT
  )}/x"
  h4 = "${trimspace(<<-END-OF-TEXT
    "
    END-OF-TEXT
  )}/y"
  c1 = "${ # say "hi
    var.x
  }/a"
  c2 = "${ // say "hi" }
    var.x
  }/b"
  c3 = "${/* say "hi"
    and { */ var.x
  }/c"
  c4 = "${join("-", [
    "a", # first "x"
    "b", // second "y" }
    /* third "z" { */ "c",
  ])}/n"
  # it's a "comment" with a } brace
  // another 'one' with a "quote"
  /* a block "comment"
     over lines { */
  d1 = { "k" = "v", "w" = "${"x"}" }
}

resource "aws_ssm_parameter" "a" {
  name  = "/x/a"
  type  = "SecureString"
  value = "hunter2"
}
