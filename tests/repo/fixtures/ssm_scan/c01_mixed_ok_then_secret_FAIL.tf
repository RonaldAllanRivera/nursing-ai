# don't "worry" about { this
// a "quote" and a } brace
/* a "quote" { and
   a } brace */
resource "aws_iam_policy" "p" {
  name        = "p" # it's "fine" }
  description = "a # not a comment // nor this /* nor this { } \" ok"
  policy      = <<-EOT
    { "a": "${var.x}", "b": "}" }
    "
  EOT
  path        = "%{if var.y}/a%{else}/b%{endif}"
  empty       = <<EOT
EOT
  esc         = "a\\"
  esc2        = "$${not} %%{not}"
  nested      = "${replace(var.x, "}", "{")}/n"
  multi = "${
    var.x
  }/c"
}

resource "aws_ssm_parameter" "a" {
  name  = "/x/a"
  type  = "SecureString"
  value = "hunter2"
}
