resource "aws_ssm_parameter" "a" {
  name             = "/x/a"
  type             = "SecureString"
  value_wo         = "set-by-hand"
  value_wo_version = 1
}
