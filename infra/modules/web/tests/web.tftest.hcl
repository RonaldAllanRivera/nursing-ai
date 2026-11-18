mock_provider "aws" {}

override_resource {
  target = aws_s3_bucket.site
  values = {
    arn                         = "arn:aws:s3:::demo-web-bucket"
    bucket                      = "demo-web-bucket"
    bucket_regional_domain_name = "demo-web-bucket.s3.ap-southeast-2.amazonaws.com"
  }
}

override_resource {
  target = aws_cloudfront_distribution.site
  values = {
    id          = "EDISTRIBUTION1"
    arn         = "arn:aws:cloudfront::123456789012:distribution/EDISTRIBUTION1"
    domain_name = "d111111abcdef8.cloudfront.net"
  }
}

override_resource {
  target = aws_cloudfront_origin_access_control.site
  values = {
    id = "EOAC123456789"
  }
}

override_resource {
  target = aws_cloudfront_function.spa_rewrite
  values = {
    arn = "arn:aws:cloudfront::123456789012:function/demo-spa-rewrite"
  }
}

variables {
  name = "demo"
}

run "bucket_not_public" {
  assert {
    condition = (
      aws_s3_bucket_public_access_block.site.block_public_acls &&
      aws_s3_bucket_public_access_block.site.block_public_policy &&
      aws_s3_bucket_public_access_block.site.ignore_public_acls &&
      aws_s3_bucket_public_access_block.site.restrict_public_buckets
    )
    error_message = "All four public access flags must be on."
  }

  assert {
    condition     = one(aws_s3_bucket_ownership_controls.site.rule).object_ownership == "BucketOwnerEnforced"
    error_message = "Ownership must be BucketOwnerEnforced."
  }

  assert {
    condition     = length(jsondecode(aws_s3_bucket_policy.site.policy).Statement) == 2
    error_message = "The bucket policy must have exactly two statements."
  }

  assert {
    condition     = length([for s in jsondecode(aws_s3_bucket_policy.site.policy).Statement : s if s.Effect == "Allow"]) == 1
    error_message = "The bucket policy must have exactly one Allow."
  }

  assert {
    condition     = [for s in jsondecode(aws_s3_bucket_policy.site.policy).Statement : s.Principal.Service if s.Effect == "Allow"][0] == "cloudfront.amazonaws.com"
    error_message = "The only Allow must be to the CloudFront service."
  }

  assert {
    condition     = [for s in jsondecode(aws_s3_bucket_policy.site.policy).Statement : s.Condition.StringEquals["AWS:SourceArn"] if s.Effect == "Allow"][0] == aws_cloudfront_distribution.site.arn
    error_message = "The Allow must be limited to this distribution's ARN."
  }

  assert {
    condition     = [for s in jsondecode(aws_s3_bucket_policy.site.policy).Statement : s.Resource if s.Effect == "Allow"][0] == "${aws_s3_bucket.site.arn}/*"
    error_message = "The Allow must cover the bucket's objects only."
  }

  assert {
    condition     = [for s in jsondecode(aws_s3_bucket_policy.site.policy).Statement : s.Action if s.Effect == "Allow"][0] == "s3:GetObject"
    error_message = "The Allow must be s3:GetObject only."
  }

  assert {
    condition     = length([for s in jsondecode(aws_s3_bucket_policy.site.policy).Statement : s if s.Effect == "Deny" && s.Condition.Bool["aws:SecureTransport"] == "false"]) == 1
    error_message = "The policy must deny requests without TLS."
  }

  assert {
    condition     = [for s in jsondecode(aws_s3_bucket_policy.site.policy).Statement : s.Principal if s.Effect == "Deny"][0] == "*" && [for s in jsondecode(aws_s3_bucket_policy.site.policy).Statement : s.Action if s.Effect == "Deny"][0] == "s3:*"
    error_message = "The TLS deny must apply to every principal and every S3 action."
  }

  assert {
    condition     = contains([for s in jsondecode(aws_s3_bucket_policy.site.policy).Statement : s.Resource if s.Effect == "Deny"][0], aws_s3_bucket.site.arn) && contains([for s in jsondecode(aws_s3_bucket_policy.site.policy).Statement : s.Resource if s.Effect == "Deny"][0], "${aws_s3_bucket.site.arn}/*")
    error_message = "The TLS deny must cover the bucket and its objects."
  }

  assert {
    condition     = length([for s in jsondecode(aws_s3_bucket_policy.site.policy).Statement : s if s.Effect == "Deny"]) == 1
    error_message = "The policy must have exactly one Deny."
  }

  assert {
    condition     = aws_s3_bucket_policy.site.bucket == aws_s3_bucket.site.id
    error_message = "The policy must be on the site bucket."
  }
}

run "cloudfront_reads_through_oac_over_https" {
  assert {
    condition     = one(aws_cloudfront_distribution.site.origin).origin_access_control_id == aws_cloudfront_origin_access_control.site.id
    error_message = "The S3 origin must use the origin access control."
  }

  assert {
    condition     = aws_cloudfront_origin_access_control.site.signing_behavior == "always" && aws_cloudfront_origin_access_control.site.signing_protocol == "sigv4" && aws_cloudfront_origin_access_control.site.origin_access_control_origin_type == "s3"
    error_message = "The OAC must sign every request with sigv4 for S3."
  }

  assert {
    condition     = one(aws_cloudfront_distribution.site.origin).domain_name == aws_s3_bucket.site.bucket_regional_domain_name
    error_message = "The origin must be the bucket."
  }

  assert {
    condition     = one(aws_cloudfront_distribution.site.default_cache_behavior).viewer_protocol_policy == "redirect-to-https"
    error_message = "The default behaviour must redirect to HTTPS."
  }

  assert {
    condition     = one(aws_cloudfront_distribution.site.default_cache_behavior).cache_policy_id == "658327ea-f89d-4fab-a63d-7e88639e58f6" && one(aws_cloudfront_distribution.site.default_cache_behavior).response_headers_policy_id == "67f7725c-6f97-4210-82d7-5512b31e9d03"
    error_message = "The default behaviour must use the CachingOptimized and SecurityHeaders managed policies."
  }

  assert {
    condition     = aws_cloudfront_distribution.site.default_root_object == "index.html" && length(aws_cloudfront_distribution.site.custom_error_response) == 0
    error_message = "Root object index.html and no custom error responses."
  }

  assert {
    condition     = output.domain_name == "d111111abcdef8.cloudfront.net" && output.distribution_id == "EDISTRIBUTION1" && output.bucket_name == "demo-web-bucket" && output.bucket_arn == "arn:aws:s3:::demo-web-bucket" && output.distribution_arn == "arn:aws:cloudfront::123456789012:distribution/EDISTRIBUTION1"
    error_message = "Outputs must come from the distribution and bucket."
  }
}

run "spa_rewrite_on_the_web_paths_only" {
  variables {
    api_origin_domain = "abc123.execute-api.ap-southeast-2.amazonaws.com"
  }

  assert {
    condition     = length(aws_cloudfront_distribution.site.origin) == 2
    error_message = "There must be a bucket origin and an API origin."
  }

  assert {
    condition     = [for a in one(aws_cloudfront_distribution.site.default_cache_behavior).function_association : a.function_arn][0] == aws_cloudfront_function.spa_rewrite.arn
    error_message = "The default behaviour must run the rewrite function."
  }

  assert {
    condition     = [for a in one(aws_cloudfront_distribution.site.default_cache_behavior).function_association : a.event_type][0] == "viewer-request"
    error_message = "The function must run on viewer-request."
  }

  assert {
    condition     = length(aws_cloudfront_distribution.site.ordered_cache_behavior) == 1
    error_message = "There must be exactly one ordered behaviour."
  }

  assert {
    condition     = length(aws_cloudfront_distribution.site.ordered_cache_behavior[0].function_association) == 0
    error_message = "The /api/* behaviour must have no function."
  }

  assert {
    condition     = aws_cloudfront_distribution.site.ordered_cache_behavior[0].path_pattern == "/api/*"
    error_message = "The ordered behaviour must be /api/*."
  }

  assert {
    condition     = aws_cloudfront_distribution.site.ordered_cache_behavior[0].cache_policy_id == "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" && aws_cloudfront_distribution.site.ordered_cache_behavior[0].origin_request_policy_id == "b689b0a8-53d0-40ab-baf2-68738e2966ac"
    error_message = "The /api/* behaviour must use CachingDisabled and AllViewerExceptHostHeader."
  }

  assert {
    condition     = length(aws_cloudfront_distribution.site.ordered_cache_behavior[0].allowed_methods) == 7 && aws_cloudfront_distribution.site.ordered_cache_behavior[0].viewer_protocol_policy == "redirect-to-https"
    error_message = "The /api/* behaviour must allow all methods and redirect to HTTPS."
  }

  assert {
    condition = (
      length([for o in aws_cloudfront_distribution.site.origin : o if o.domain_name == "abc123.execute-api.ap-southeast-2.amazonaws.com"]) == 1 &&
      [for o in aws_cloudfront_distribution.site.origin : o.origin_id if o.domain_name == "abc123.execute-api.ap-southeast-2.amazonaws.com"][0] == aws_cloudfront_distribution.site.ordered_cache_behavior[0].target_origin_id
    )
    error_message = "The /api/* behaviour must target the API origin."
  }

  assert {
    condition     = [for o in aws_cloudfront_distribution.site.origin : one(o.custom_origin_config).origin_protocol_policy if o.domain_name == "abc123.execute-api.ap-southeast-2.amazonaws.com"][0] == "https-only" && contains([for o in aws_cloudfront_distribution.site.origin : one(o.custom_origin_config).origin_ssl_protocols if o.domain_name == "abc123.execute-api.ap-southeast-2.amazonaws.com"][0], "TLSv1.2")
    error_message = "The API origin must be https-only over TLSv1.2."
  }

  assert {
    condition     = one(aws_cloudfront_distribution.site.default_cache_behavior).target_origin_id != aws_cloudfront_distribution.site.ordered_cache_behavior[0].target_origin_id
    error_message = "The default behaviour must stay on the bucket origin."
  }
}

run "no_api_behaviour_without_an_api_domain" {
  command = plan

  assert {
    condition     = length(aws_cloudfront_distribution.site.ordered_cache_behavior) == 0
    error_message = "No ordered behaviours without an API domain."
  }

  assert {
    condition     = length(aws_cloudfront_distribution.site.origin) == 1
    error_message = "Only the bucket origin without an API domain."
  }
}

run "api_origin_with_a_scheme_is_refused" {
  command = plan

  variables {
    api_origin_domain = "https://abc123.execute-api.ap-southeast-2.amazonaws.com"
  }

  expect_failures = [var.api_origin_domain]
}

run "old_site_files_expire" {
  command = plan

  assert {
    condition     = one(aws_s3_bucket_lifecycle_configuration.site.rule).status == "Enabled" && one(one(aws_s3_bucket_lifecycle_configuration.site.rule).noncurrent_version_expiration).noncurrent_days == 30
    error_message = "Noncurrent versions must expire after 30 days."
  }

  assert {
    condition     = one(one(aws_s3_bucket_lifecycle_configuration.site.rule).abort_incomplete_multipart_upload).days_after_initiation == 7
    error_message = "Incomplete multipart uploads must be aborted after 7 days."
  }
}

run "api_origin_is_exposed_only_when_the_route_is_on" {
  command = plan

  variables {
    api_origin_domain = "abc123.execute-api.ap-southeast-2.amazonaws.com"
  }

  assert {
    condition     = output.api_origin_domain == "abc123.execute-api.ap-southeast-2.amazonaws.com"
    error_message = "api_origin_domain must be the API origin the distribution has."
  }
}

run "no_api_origin_without_an_api_domain" {
  command = plan

  assert {
    condition     = output.api_origin_domain == null
    error_message = "api_origin_domain must be null when the route is off."
  }
}

# ---------------------------------------------------------------------------
# Custom domain (the certificate itself is made by the caller, in us-east-1)
# ---------------------------------------------------------------------------

run "custom_domain_off_by_default" {
  assert {
    condition     = length(aws_cloudfront_distribution.site.aliases) == 0 && length(output.aliases) == 0
    error_message = "With no custom_domain the distribution has no alias."
  }

  assert {
    condition     = one(aws_cloudfront_distribution.site.viewer_certificate).cloudfront_default_certificate == true
    error_message = "With no custom_domain the distribution keeps the cloudfront.net certificate."
  }
}

run "custom_domain_adds_the_alias_and_the_certificate" {
  variables {
    custom_domain   = "sourceline.example.com"
    certificate_arn = "arn:aws:acm:us-east-1:123456789012:certificate/11111111-2222-3333-4444-555555555555"
  }

  assert {
    condition     = aws_cloudfront_distribution.site.aliases == toset(["sourceline.example.com"]) && join(",", output.aliases) == "sourceline.example.com"
    error_message = "The distribution must answer to the domain."
  }

  assert {
    condition     = one(aws_cloudfront_distribution.site.viewer_certificate).acm_certificate_arn == var.certificate_arn && one(aws_cloudfront_distribution.site.viewer_certificate).cloudfront_default_certificate != true
    error_message = "The distribution must use the ACM certificate."
  }

  assert {
    condition     = one(aws_cloudfront_distribution.site.viewer_certificate).ssl_support_method == "sni-only" && one(aws_cloudfront_distribution.site.viewer_certificate).minimum_protocol_version == "TLSv1.2_2021"
    error_message = "SNI only (a dedicated IP costs $600 a month) and TLS 1.2 or newer."
  }
}

run "custom_domain_needs_a_certificate" {
  command = plan

  variables {
    custom_domain = "sourceline.example.com"
  }

  expect_failures = [var.certificate_arn]
}

run "certificate_needs_a_custom_domain" {
  command = plan

  variables {
    certificate_arn = "arn:aws:acm:us-east-1:123456789012:certificate/11111111-2222-3333-4444-555555555555"
  }

  expect_failures = [var.certificate_arn]
}

run "certificate_must_be_in_us_east_1" {
  command = plan

  variables {
    custom_domain   = "sourceline.example.com"
    certificate_arn = "arn:aws:acm:ap-southeast-2:123456789012:certificate/11111111-2222-3333-4444-555555555555"
  }

  expect_failures = [var.certificate_arn]
}

run "custom_domain_must_be_a_host_name" {
  command = plan

  variables {
    custom_domain   = "https://sourceline.example.com"
    certificate_arn = "arn:aws:acm:us-east-1:123456789012:certificate/11111111-2222-3333-4444-555555555555"
  }

  expect_failures = [var.custom_domain]
}
