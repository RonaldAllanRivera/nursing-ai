output "api_endpoint" {
  description = "Base URL of the HTTP API."
  value       = aws_apigatewayv2_api.this.api_endpoint
}

output "http_api_id" {
  description = "ID of the HTTP API."
  value       = aws_apigatewayv2_api.this.id
}

output "api_function_name" {
  description = "Name of the API function."
  value       = aws_lambda_function.api.function_name
}

output "worker_function_name" {
  description = "Name of the queue worker function."
  value       = aws_lambda_function.worker.function_name
}

output "api_role_name" {
  description = "Name of the API function's role."
  value       = aws_iam_role.api.name
}

output "api_role_arn" {
  description = "ARN of the API function's role."
  value       = aws_iam_role.api.arn
}

output "worker_role_name" {
  description = "Name of the worker function's role."
  value       = aws_iam_role.worker.name
}

output "worker_role_arn" {
  description = "ARN of the worker function's role."
  value       = aws_iam_role.worker.arn
}

output "queue_url" {
  description = "URL of the draft jobs queue."
  value       = aws_sqs_queue.jobs.url
}

output "queue_arn" {
  description = "ARN of the draft jobs queue."
  value       = aws_sqs_queue.jobs.arn
}

output "dlq_name" {
  description = "Name of the dead-letter queue."
  value       = aws_sqs_queue.dlq.name
}

output "dlq_arn" {
  description = "ARN of the dead-letter queue."
  value       = aws_sqs_queue.dlq.arn
}
