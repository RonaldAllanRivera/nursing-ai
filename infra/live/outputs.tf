output "site_url" {
  description = "Address of the web site."
  value       = "https://${module.web.domain_name}"
}

output "api_endpoint" {
  description = "Base URL of the HTTP API, for calls that do not go through the web site."
  value       = module.compute.api_endpoint
}

output "web_bucket_name" {
  description = "Name of the bucket the web build is uploaded to."
  value       = module.web.bucket_name
}

output "distribution_id" {
  description = "ID of the CloudFront distribution, used to invalidate the cache after an upload."
  value       = module.web.distribution_id
}

output "queue_url" {
  description = "URL of the draft jobs queue."
  value       = module.compute.queue_url
}

output "ops_function_name" {
  description = "Name of the ops function a deploy invokes for migrate, seed-demo and smoke."
  value       = module.compute.ops_function_name
}

output "http_api_id" {
  description = "ID of the HTTP API, for a deploy to check that the 5xx alarm watches it."
  value       = module.compute.http_api_id
}

output "dlq_name" {
  description = "Name of the dead-letter queue, for a deploy to check that the dead-jobs alarm watches it."
  value       = module.compute.dlq_name
}

output "alarm_names" {
  description = "Names of the alarms, keyed api_5xx, dead_jobs and ai_spend."
  value       = module.ops.alarm_names
}
