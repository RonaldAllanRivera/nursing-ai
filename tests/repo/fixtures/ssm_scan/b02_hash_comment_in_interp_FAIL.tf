resource "aws_ssm_parameter" "a" {
  name = "${ # {
    var.x
  }/a"
  type  = "SecureString"
  value = "hunter2"
} # "}"
