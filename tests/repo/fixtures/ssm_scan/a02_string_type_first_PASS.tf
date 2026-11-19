resource "aws_ssm_parameter" "a" {
  name  = "/x/a"
  type  = "String"
  value = var.site_url
}
