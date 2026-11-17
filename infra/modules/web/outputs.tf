output "bucket_name" {
  value       = aws_s3_bucket.site.bucket
  description = "Name of the bucket the web build is uploaded to."
}

output "bucket_arn" {
  value       = aws_s3_bucket.site.arn
  description = "ARN of the bucket the web build is uploaded to."
}

output "distribution_id" {
  value       = aws_cloudfront_distribution.site.id
  description = "ID of the CloudFront distribution, used to invalidate the cache after an upload."
}

output "distribution_arn" {
  value       = aws_cloudfront_distribution.site.arn
  description = "ARN of the CloudFront distribution."
}

output "domain_name" {
  value       = aws_cloudfront_distribution.site.domain_name
  description = "The cloudfront.net host name the site is served from."
}

output "aliases" {
  value       = sort(tolist(aws_cloudfront_distribution.site.aliases))
  description = "Host names the distribution answers to besides its cloudfront.net name."
}

output "api_origin_domain" {
  value       = one([for o in aws_cloudfront_distribution.site.origin : o.domain_name if o.origin_id == local.api_origin_id])
  description = "Host name of the HTTP API origin the distribution really has, or null when the /api/* route is off."
}
