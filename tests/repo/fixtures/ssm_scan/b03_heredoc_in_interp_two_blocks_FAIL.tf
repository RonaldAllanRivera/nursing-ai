resource "aws_ssm_parameter" "a" {
  name = "${trimspace(<<EOT
{
EOT
  )}/a"
  type  = "SecureString"
  value = "hunter2"
}

locals {
  y = "${trimspace(<<EOT
}
EOT
  )}/b"
}
