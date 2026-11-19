resource "aws_ssm_parameter" "a" {
  name     = "/x/a"
  type     = "SecureString"
  value_wo = "x"
  tags     = { value = "label" }
}
