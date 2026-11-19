resource "aws_ssm_parameter" "a" {
  name        = "/x/a"
  description = <<ÉOT
}
{
ÉOT
  type        = "SecureString"
  value       = "hunter2"
}
