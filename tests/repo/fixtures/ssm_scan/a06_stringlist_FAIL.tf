resource "aws_ssm_parameter" "a" {
  name  = "/x/a"
  type  = "StringList"
  value = "a,b"
}
