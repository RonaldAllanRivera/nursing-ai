resource "aws_ssm_parameter" "a" {
  name        = "/x/a"
  description = "costs $$${"
  type        = "SecureString"
  value       = "hunter2"
} # "}"
