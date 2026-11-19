resource "aws_ssm_parameter" "a" {
  name  = "/x/a"
  value = var.site_url
  type  = "String"
}
