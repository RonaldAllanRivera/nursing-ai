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
