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
