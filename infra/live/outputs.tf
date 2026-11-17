output "site_url" {
  description = "Address of the web site: the custom domain once domain_validated is true, the cloudfront.net name before."
  value       = local.site_url
}

output "dns_records" {
  description = "The two CNAME records to add in the DNS provider as DNS only (not proxied): certificate_validation and site. Empty when domain_name is null."
  value = var.domain_name == null ? {} : {
    certificate_validation = {
      name  = trimsuffix(one(aws_acm_certificate.site[0].domain_validation_options).resource_record_name, ".")
      type  = one(aws_acm_certificate.site[0].domain_validation_options).resource_record_type
      value = trimsuffix(one(aws_acm_certificate.site[0].domain_validation_options).resource_record_value, ".")
    }
    site = {
      name  = var.domain_name
      type  = "CNAME"
      value = module.web.domain_name
    }
  }
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
