resource "aws_ssm_parameter" "a" {
  name        = "/x/a"
  type        = "SecureString"
  description = <<-EOF
    value = "just prose"
  EOF
  value_wo    = "x"
}
