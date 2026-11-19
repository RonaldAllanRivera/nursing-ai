resource "aws_ssm_parameter" "a" {
  name = "${lookup({
    type = "String"
  }, "type")}/a"
  type  = "SecureString"
  value = "hunter2"
}
