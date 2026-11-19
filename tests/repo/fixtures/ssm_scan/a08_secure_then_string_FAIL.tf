resource "aws_ssm_parameter" "b" {
  name  = "/x/b"
  value = "hunter2"
  type  = "SecureString"
  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "a" {
  name  = "/x/a"
  type  = "String"
  value = var.site_url
}
