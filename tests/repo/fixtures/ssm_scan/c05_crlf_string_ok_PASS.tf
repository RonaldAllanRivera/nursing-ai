resource "aws_ssm_parameter" "a" {
  name  = "${var.prefix}/site_url" # "}"
  type  = "String"
  value = "https://example.test/${var.x}"
  tags = {
    note = "a { b } c"
  }
}
