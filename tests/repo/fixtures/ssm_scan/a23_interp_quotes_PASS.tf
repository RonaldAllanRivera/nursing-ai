resource "aws_ssm_parameter" "a" {
  name  = "/x/${var.m["k"]}/a"
  type  = "String"
  value = var.site_url
}
