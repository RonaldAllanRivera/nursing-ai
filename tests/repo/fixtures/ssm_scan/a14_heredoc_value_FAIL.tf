resource "aws_ssm_parameter" "a" {
  name  = "/x/a"
  type  = "SecureString"
  value = <<-EOF
    hunter2
  EOF
}
