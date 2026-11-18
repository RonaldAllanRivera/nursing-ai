output "parameter_names" {
  description = "Names of the secret parameters, keyed anthropic-api-key, google-client-id and google-client-secret."
  value       = { for k, p in aws_ssm_parameter.secret : k => p.name }
}

output "parameter_arns" {
  description = "ARNs of the secret parameters, keyed anthropic-api-key, google-client-id and google-client-secret."
  value       = { for k, p in aws_ssm_parameter.secret : k => p.arn }
}

output "api_log_group_name" {
  description = "Name of the API function's log group."
  value       = aws_cloudwatch_log_group.api.name
}

output "worker_log_group_name" {
  description = "Name of the worker function's log group."
  value       = aws_cloudwatch_log_group.worker.name
}

output "api_access_log_group_name" {
  description = "Name of the log group for the HTTP API access log."
  value       = aws_cloudwatch_log_group.api_access.name
}

output "api_access_log_group_arn" {
  description = "ARN of the log group for the HTTP API access log."
  value       = aws_cloudwatch_log_group.api_access.arn
}

output "alarm_topic_arn" {
  description = "ARN of the topic the alarms notify."
  value       = aws_sns_topic.alarms.arn
}

output "site_url_parameter_name" {
  description = "Name of the plain String parameter that holds the site address."
  value       = aws_ssm_parameter.site_url.name
}

output "site_url_parameter_arn" {
  description = "ARN of the plain String parameter that holds the site address."
  value       = aws_ssm_parameter.site_url.arn
}

output "bootstrap_admin_email_parameter_name" {
  description = "Name of the SecureString that holds the bootstrap admin email."
  value       = aws_ssm_parameter.bootstrap_admin_email.name
}

output "bootstrap_admin_email_parameter_arn" {
  description = "ARN of the SecureString that holds the bootstrap admin email."
  value       = aws_ssm_parameter.bootstrap_admin_email.arn
}

output "ops_log_group_name" {
  description = "Name of the ops function's log group."
  value       = aws_cloudwatch_log_group.ops.name
}

output "alarm_names" {
  description = "Names of the alarms, keyed api_5xx, dead_jobs and ai_spend, for a deploy to check."
  value = {
    api_5xx   = aws_cloudwatch_metric_alarm.api_5xx.alarm_name
    dead_jobs = aws_cloudwatch_metric_alarm.dlq_depth.alarm_name
    ai_spend  = aws_cloudwatch_metric_alarm.ai_spend.alarm_name
  }
}

output "site_url_parameter_value" {
  description = "The site address stored in the site-url parameter (public, so safe to show: the provider marks every parameter value sensitive)."
  value       = nonsensitive(aws_ssm_parameter.site_url.value)
}
