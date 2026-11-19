resource "aws_ssm_parameter" "a" {
  name  = "/x/a"
  /*
  type = "String"
  */
  type  = "SecureString"
  value = "hunter2"
}
