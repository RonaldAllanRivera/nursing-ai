resource "aws_ssm_parameter" "a" {
  name  = "/x/a"
  type  = "SecureString"
  value = "pa#ss//word"
}
