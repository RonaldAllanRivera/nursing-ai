resource "aws_ssm_parameter" "a" {
  name  = "/x/a"
  type  = var.kind
  value = "hunter2"
}
