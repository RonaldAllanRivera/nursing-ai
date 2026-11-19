resource "aws_ssm_parameter" "a" {
  name  = "/x/a"
  type  = var.public ? "String" : "SecureString"
  value = "hunter2"
}
