locals {
  secret_keys = toset(["anthropic-api-key", "google-client-id", "google-client-secret"])
}

# The owner sets the real values by hand. Terraform sends a write-only
# placeholder, never reads a value back, and never keeps one in its state.
resource "aws_ssm_parameter" "secret" {
  for_each = local.secret_keys

  name             = "${var.parameter_path}/${each.key}"
  description      = "Set with aws ssm put-parameter --overwrite. Terraform never reads this value."
  type             = "SecureString"
  value_wo         = "set-by-hand"
  value_wo_version = 1
}

# The site address is public (the address of the site itself), so it is a plain
# String that Terraform writes, and it changes when the address does (check.sh
# lets a plain `value` only on a String).
resource "aws_ssm_parameter" "site_url" {
  name        = "${var.parameter_path}/site-url"
  description = "Address of the site (an origin, no path), written by Terraform. The app reads it at cold start."
  type        = "String"
  value       = var.site_url
}

# Set by hand like the secrets above. The placeholder is a well-formed email
# (exactly one @) because the app checks the setting at every cold start, and
# would otherwise fail to start until the owner sets the real address.
resource "aws_ssm_parameter" "bootstrap_admin_email" {
  name             = "${var.parameter_path}/bootstrap-admin-email"
  description      = "Set with aws ssm put-parameter --overwrite. Terraform never reads this value."
  type             = "SecureString"
  value_wo         = var.bootstrap_admin_email_placeholder
  value_wo_version = 1
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/${var.api_function_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/aws/lambda/${var.worker_function_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "ops" {
  name              = "/aws/lambda/${var.ops_function_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "api_access" {
  name              = "/aws/apigateway/${var.name}-access"
  retention_in_days = var.log_retention_days
}

# The topic is not encrypted. CloudWatch alarms cannot publish to a topic that
# uses the AWS-managed SNS key, a customer managed key costs $1 a month, and
# the alarm notices carry no patient data.
#trivy:ignore:AWS-0095
resource "aws_sns_topic" "alarms" {
  name = "${var.name}-alarms"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

resource "aws_cloudwatch_metric_alarm" "api_5xx" {
  alarm_name          = "${var.name}-api-5xx"
  alarm_description   = "The API returned 5 or more server errors within 5 minutes."
  namespace           = "AWS/ApiGateway"
  metric_name         = "5xx"
  dimensions          = { ApiId = var.http_api_id, Stage = var.http_api_stage }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 5
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "dlq_depth" {
  alarm_name          = "${var.name}-dead-jobs"
  alarm_description   = "A job failed all its attempts and is waiting in the dead-letter queue."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = var.dlq_name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "ai_spend" {
  alarm_name          = "${var.name}-ai-spend"
  alarm_description   = "AI spend over the last day reached the alarm level."
  namespace           = var.ai_spend_metric_namespace
  metric_name         = var.ai_spend_metric_name
  statistic           = "Sum"
  period              = 86400
  evaluation_periods  = 1
  threshold           = var.ai_daily_spend_alarm_usd
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
}
