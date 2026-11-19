resource "aws_ssm_parameter" "a" {
  name  = "/x/a"
  type  = "String"
  value = var.site_url
}

locals {
  doc = <<-EOF
    resource "aws_ssm_parameter" "fake" {
      value = "not real"
    }
  EOF
}
