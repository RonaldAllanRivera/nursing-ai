resource "aws_ssm_parameter" "a" {
  name        = "/x/a"
  type        = "SecureString"
  description = <<-EOT
    type = "String"
  EOT
  value       = "hunter2"
}
