resource "aws_ssm_parameter" "a" {
  name = "/x/a"
  description = <<EOT
${[
  EOT
][0]}
{
EOT
type  = "SecureString"
value = "hunter2"
}
