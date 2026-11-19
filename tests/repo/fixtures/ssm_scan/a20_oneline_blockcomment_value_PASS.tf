resource "aws_ssm_parameter" "a" {
  name     = "/x/a"
  type     = "SecureString"
  /* value = "old" */
  value_wo = "x"
}
