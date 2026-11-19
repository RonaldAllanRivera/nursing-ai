resource "aws_ssm_parameter" "a" {
  name  = "/x/a"
  type  = "String"
  value = var.site_url
}

resource "aws_ssm_parameter" "b" {
  name  = "/x/b"
  type  = "SecureString"
  value = "hunter2"
}
