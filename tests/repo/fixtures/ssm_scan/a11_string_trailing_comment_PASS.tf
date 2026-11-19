resource "aws_ssm_parameter" "a" {
  name  = "/x/a"
  type  = "String" # public
  value = var.site_url
}
