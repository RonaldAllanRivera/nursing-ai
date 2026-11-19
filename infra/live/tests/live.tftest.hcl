# Every module sits under one mocked AWS provider; the random provider is real.
# A mock gives every resource of a type the same computed values, so the
# overrides give each role and secret parameter its own ARN. Without them a
# swapped pair would pass because both items look alike. The checks that bite
# are the ones the modules make on their inputs: the brake wants each role's
# name to end its ARN, and compute wants each parameter's ARN to end with its
# name. A role's ARN override names the demo roles, so the prod run (plan
# mode, where override values for computed attributes are not used) is not
# affected by it.
mock_provider "aws" {
  mock_resource "aws_vpc" {
    defaults = {
      ipv6_cidr_block = "2001:db8:1234:5600::/56"
    }
  }

  # Other modules pass these ARNs on, and the provider checks their shape.
  mock_resource "aws_iam_role" {
    defaults = {
      arn = "arn:aws:iam::123456789012:role/mock"
    }
  }

  mock_resource "aws_iam_policy" {
    defaults = {
      arn = "arn:aws:iam::123456789012:policy/mock"
    }
  }

  mock_resource "aws_cloudfront_function" {
    defaults = {
      arn = "arn:aws:cloudfront::123456789012:function/mock"
    }
  }

  mock_resource "aws_sns_topic" {
    defaults = {
      arn = "arn:aws:sns:ap-southeast-2:123456789012:mock"
    }
  }
}

# The custom-domain certificate lives in us-east-1, which is a second provider.
mock_provider "aws" {
  alias = "us_east_1"
}

override_resource {
  target = module.compute.aws_iam_role.api
  values = {
    arn = "arn:aws:iam::123456789012:role/nursing-ai-demo-api"
  }
}

override_resource {
  target = module.compute.aws_iam_role.worker
  values = {
    arn = "arn:aws:iam::123456789012:role/nursing-ai-demo-worker"
  }
}

override_resource {
  target = module.compute.aws_iam_role.ops
  values = {
    arn = "arn:aws:iam::123456789012:role/nursing-ai-demo-ops"
  }
}

override_resource {
  target = module.compute.aws_apigatewayv2_api.this
  values = {
    id            = "abc123"
    execution_arn = "arn:aws:execute-api:ap-southeast-2:123456789012:abc123"
    api_endpoint  = "https://abc123.execute-api.ap-southeast-2.amazonaws.com"
  }
}

override_resource {
  target = module.aurora.aws_ssm_parameter.database_url
  values = {
    arn = "arn:aws:ssm:ap-southeast-2:123456789012:parameter/nursing-ai/demo/database-url"
  }
}

override_resource {
  target = module.ops.aws_ssm_parameter.secret["anthropic-api-key"]
  values = {
    arn = "arn:aws:ssm:ap-southeast-2:123456789012:parameter/nursing-ai/demo/anthropic-api-key"
  }
}

override_resource {
  target = module.ops.aws_ssm_parameter.secret["google-client-id"]
  values = {
    arn = "arn:aws:ssm:ap-southeast-2:123456789012:parameter/nursing-ai/demo/google-client-id"
  }
}

override_resource {
  target = module.ops.aws_ssm_parameter.secret["google-client-secret"]
  values = {
    arn = "arn:aws:ssm:ap-southeast-2:123456789012:parameter/nursing-ai/demo/google-client-secret"
  }
}

override_resource {
  target = module.ops.aws_ssm_parameter.site_url
  values = {
    arn = "arn:aws:ssm:ap-southeast-2:123456789012:parameter/nursing-ai/demo/site-url"
  }
}

override_resource {
  target = module.ops.aws_ssm_parameter.bootstrap_admin_email
  values = {
    arn = "arn:aws:ssm:ap-southeast-2:123456789012:parameter/nursing-ai/demo/bootstrap-admin-email"
  }
}

override_resource {
  target = module.ops.aws_cloudwatch_log_group.api_access
  values = {
    arn = "arn:aws:logs:ap-southeast-2:123456789012:log-group:/aws/apigateway/nursing-ai-demo-access"
  }
}

variables {
  image_uri   = "123456789012.dkr.ecr.ap-southeast-2.amazonaws.com/nursing-ai:test"
  alert_email = "alerts@example.com"
}

# A test can read a module's outputs but not its resources, so each check below
# goes through an output. Where a module only uses an input, its own validation
# is what rejects a wrong one (the brake checks that each role's name belongs
# to its ARN; the web module refuses an API address that has a scheme).

run "names_follow_a_prod_environment" {
  command = plan

  # Its own state, so nothing a demo run left behind (such as a role ARN)
  # reaches it.
  state_key = "prod"

  variables {
    environment = "prod"
  }

  assert {
    condition     = module.compute.api_function_name == "nursing-ai-prod-api" && module.compute.worker_function_name == "nursing-ai-prod-worker"
    error_message = "the function names must follow the environment"
  }
  assert {
    condition     = module.ops.api_log_group_name == "/aws/lambda/nursing-ai-prod-api" && module.ops.worker_log_group_name == "/aws/lambda/nursing-ai-prod-worker"
    error_message = "the log groups must follow the environment"
  }
  assert {
    condition     = module.aurora.database_url_parameter_name == "/nursing-ai/prod/database-url" && module.ops.parameter_names["google-client-id"] == "/nursing-ai/prod/google-client-id"
    error_message = "the parameters must live under the environment's path"
  }
}

run "stack_wires_together" {
  # Apply mode: the brake and compute validations run on the overridden (and so
  # distinct) role and parameter ARNs, which exist only after apply.
  assert {
    condition     = length(module.brake.target_role_names) == 2 && module.brake.target_role_names == toset([module.compute.api_role_name, module.compute.worker_role_name])
    error_message = "the brake must target exactly compute's API role and worker role"
  }
  assert {
    condition     = module.aurora.database_url_parameter_name == "/nursing-ai/demo/database-url"
    error_message = "the database URL parameter must live under the environment's path"
  }
  assert {
    condition = (
      length(module.ops.parameter_names) == 3
      && module.ops.parameter_names["anthropic-api-key"] == "/nursing-ai/demo/anthropic-api-key"
      && module.ops.parameter_names["google-client-id"] == "/nursing-ai/demo/google-client-id"
      && module.ops.parameter_names["google-client-secret"] == "/nursing-ai/demo/google-client-secret"
    )
    error_message = "the secret parameters must live under the environment's path"
  }
}

run "lambdas_log_to_the_groups_ops_made" {
  # Plan mode: every value here comes from configuration.
  command = plan

  # Ops makes each log group from the function name the locals gave it; the
  # function itself is named by compute. The two must agree, or the function
  # would write to a group of its own and ignore the one with retention.
  assert {
    condition     = module.compute.function_log_groups.api == module.ops.api_log_group_name && module.compute.function_log_groups.worker == module.ops.worker_log_group_name
    error_message = "each function must log to the group ops made for it"
  }
  assert {
    condition     = module.compute.function_log_groups.api != module.compute.function_log_groups.worker
    error_message = "the two functions must log to different groups"
  }
  assert {
    condition     = module.ops.api_log_group_name == "/aws/lambda/${module.compute.api_function_name}"
    error_message = "ops's API log group must be named after compute's API function"
  }
  assert {
    condition     = module.ops.worker_log_group_name == "/aws/lambda/${module.compute.worker_function_name}"
    error_message = "ops's worker log group must be named after compute's worker function"
  }
  assert {
    condition     = module.ops.api_log_group_name != module.ops.worker_log_group_name
    error_message = "the two log groups must differ"
  }
}

run "site_routes_api_calls_to_the_http_api" {
  # The web module only creates its /api/* behaviour and origin when it is
  # given an API host, and it refuses a host that carries https://. The run
  # passing means the root hands it the bare host from compute's endpoint.
  assert {
    condition     = module.web.api_origin_domain != null && module.web.api_origin_domain == trimprefix(module.compute.api_endpoint, "https://")
    error_message = "the distribution must have the HTTP API's host name as its API origin"
  }
  assert {
    condition     = output.api_endpoint == "https://abc123.execute-api.ap-southeast-2.amazonaws.com"
    error_message = "api_endpoint must be compute's endpoint, scheme included"
  }
  assert {
    condition     = output.site_url == "https://${module.web.domain_name}" && startswith(output.site_url, "https://")
    error_message = "site_url must be https:// plus the distribution's domain"
  }
  assert {
    condition     = output.web_bucket_name == module.web.bucket_name && output.distribution_id == module.web.distribution_id && output.queue_url == module.compute.queue_url
    error_message = "the outputs must come from the web and compute modules"
  }
}

run "ops_function_is_wired_to_its_log_group_and_outputs" {
  assert {
    condition     = module.compute.function_log_groups.ops == module.ops.ops_log_group_name && module.ops.ops_log_group_name == "/aws/lambda/${module.compute.ops_function_name}"
    error_message = "the ops function must log to the group ops made for it"
  }
  assert {
    condition     = output.ops_function_name == "nursing-ai-demo-ops" && output.http_api_id == "abc123" && output.dlq_name == "${module.compute.dlq_name}"
    error_message = "the deploy outputs must come from compute"
  }
  assert {
    condition     = output.alarm_names == { api_5xx = "nursing-ai-demo-api-5xx", dead_jobs = "nursing-ai-demo-dead-jobs", ai_spend = "nursing-ai-demo-ai-spend" }
    error_message = "alarm_names must name the three alarms"
  }
  assert {
    condition     = !contains(module.brake.target_role_names, module.compute.ops_role_name)
    error_message = "the ops role stays outside the brake"
  }
}

run "site_url_parameter_holds_the_distribution_address" {
  assert {
    condition     = module.ops.site_url_parameter_name == "/nursing-ai/demo/site-url" && module.ops.bootstrap_admin_email_parameter_name == "/nursing-ai/demo/bootstrap-admin-email"
    error_message = "the new parameters live under the environment's path"
  }
  assert {
    condition     = module.ops.site_url_parameter_value == "https://${module.web.domain_name}" && module.ops.site_url_parameter_value == output.site_url
    error_message = "the site-url parameter must be https:// plus the distribution's domain, the same as the site_url output"
  }
}

run "custom_domain_off_by_default" {
  assert {
    condition     = length(aws_acm_certificate.site) == 0 && length(aws_acm_certificate_validation.site) == 0
    error_message = "With no domain_name there is no certificate and nothing to validate."
  }
  assert {
    condition     = length(output.dns_records) == 0 && length(module.web.aliases) == 0
    error_message = "With no domain_name there are no DNS records and no alias."
  }
  assert {
    condition     = output.site_url == "https://${module.web.domain_name}" && module.ops.site_url_parameter_value == output.site_url
    error_message = "site-url stays the CloudFront domain."
  }
}

run "custom_domain_waits_for_the_validation_records" {
  variables {
    domain_name = "sourceline.example.com"
  }

  override_resource {
    target = aws_acm_certificate.site[0]
    values = {
      arn = "arn:aws:acm:us-east-1:123456789012:certificate/11111111-2222-3333-4444-555555555555"
      domain_validation_options = [{
        domain_name           = "sourceline.example.com"
        resource_record_name  = "_abc123.sourceline.example.com."
        resource_record_type  = "CNAME"
        resource_record_value = "_def456.acm-validations.aws."
      }]
    }
  }

  assert {
    condition     = aws_acm_certificate.site[0].domain_name == "sourceline.example.com" && aws_acm_certificate.site[0].validation_method == "DNS"
    error_message = "The certificate is for the domain, validated by DNS."
  }
  assert {
    condition     = length(aws_acm_certificate_validation.site) == 0
    error_message = "Nothing may wait for DNS before domain_validated is set."
  }
  assert {
    condition     = length(module.web.aliases) == 0
    error_message = "The distribution has no alias until domain_validated."
  }
  assert {
    condition     = output.site_url == "https://${module.web.domain_name}" && module.ops.site_url_parameter_value == "https://${module.web.domain_name}"
    error_message = "site-url stays the CloudFront domain until domain_validated."
  }
  assert {
    condition     = output.dns_records.certificate_validation == { name = "_abc123.sourceline.example.com", type = "CNAME", value = "_def456.acm-validations.aws" }
    error_message = "The validation record is the certificate's, without the trailing dots."
  }
  assert {
    condition     = output.dns_records.site == { name = "sourceline.example.com", type = "CNAME", value = module.web.domain_name }
    error_message = "The site record points the domain at the distribution."
  }
}

run "custom_domain_adds_the_alias_and_a_us_east_1_certificate" {
  variables {
    domain_name      = "sourceline.example.com"
    domain_validated = true
  }

  override_resource {
    target = aws_acm_certificate.site[0]
    values = {
      arn = "arn:aws:acm:us-east-1:123456789012:certificate/11111111-2222-3333-4444-555555555555"
      domain_validation_options = [{
        domain_name           = "sourceline.example.com"
        resource_record_name  = "_abc123.sourceline.example.com."
        resource_record_type  = "CNAME"
        resource_record_value = "_def456.acm-validations.aws."
      }]
    }
  }

  override_resource {
    target = aws_acm_certificate_validation.site[0]
    values = {
      certificate_arn = "arn:aws:acm:us-east-1:123456789012:certificate/11111111-2222-3333-4444-555555555555"
    }
  }

  assert {
    condition     = startswith(aws_acm_certificate_validation.site[0].certificate_arn, "arn:aws:acm:us-east-1:")
    error_message = "The certificate is in us-east-1."
  }
  assert {
    condition     = join(",", module.web.aliases) == "sourceline.example.com"
    error_message = "The distribution answers to the domain."
  }
  assert {
    condition     = output.site_url == "https://sourceline.example.com" && module.ops.site_url_parameter_value == "https://sourceline.example.com"
    error_message = "site-url and the site_url output become the custom domain."
  }
  assert {
    condition     = output.dns_records.site.value == module.web.domain_name
    error_message = "The DNS records stay in the output once validated."
  }
}

run "domain_name_must_be_a_host_name" {
  command = plan

  variables {
    domain_name = "https://sourceline.example.com/"
  }

  expect_failures = [var.domain_name]
}

run "domain_name_has_no_trailing_dot" {
  command = plan

  variables {
    domain_name = "sourceline.example.com."
  }

  expect_failures = [var.domain_name]
}

run "domain_name_is_lowercase" {
  command = plan

  variables {
    domain_name = "Sourceline.example.com"
  }

  expect_failures = [var.domain_name]
}

run "domain_validated_needs_a_domain_name" {
  command = plan

  variables {
    domain_validated = true
  }

  expect_failures = [var.domain_validated]
}

run "names_follow_the_environment" {
  command = plan

  assert {
    condition     = module.compute.api_function_name == "nursing-ai-demo-api" && module.compute.worker_function_name == "nursing-ai-demo-worker"
    error_message = "the functions must be nursing-ai-demo-api and nursing-ai-demo-worker"
  }
}

run "alert_email_must_contain_an_at_sign" {
  command = plan

  variables {
    alert_email = "not-an-email"
  }

  expect_failures = [var.alert_email]
}

run "alert_email_is_sensitive" {
  command = plan

  # The deploy runs in public CI logs, and a plan prints every plain value.
  assert {
    condition     = issensitive(var.alert_email)
    error_message = "alert_email must be sensitive so a plan never prints it"
  }
}

run "queue_url_is_sensitive" {
  command = plan

  # An SQS queue URL carries the account id, and terraform apply prints every
  # output in a public CI log.
  assert {
    condition     = issensitive(output.queue_url)
    error_message = "queue_url must be sensitive so an apply never prints the account id"
  }
}

run "image_uri_is_sensitive" {
  command = plan

  # Its registry host carries the account id, and every deploy changes it, so a
  # plan in a public CI log would print it each time.
  assert {
    condition     = issensitive(var.image_uri)
    error_message = "image_uri must be sensitive so a plan never prints the account id"
  }
}

run "image_uri_output_is_the_deployed_image" {
  command = plan

  # A pull request's plan reads it back so that its plan keeps the image that
  # is live; it carries the account id, and the plan's log is public.
  assert {
    condition     = output.image_uri == var.image_uri && issensitive(output.image_uri)
    error_message = "image_uri must be an output, sensitive, equal to the image applied"
  }
}

run "the_demo_answers_from_the_recorded_drafts" {
  command = plan

  # No live AI on the demo until the owner says so: the default is replay, so
  # neither a deploy nor a pull request's plan has to remember to set it.
  assert {
    condition     = var.ai_mode == "replay"
    error_message = "ai_mode must default to replay"
  }
}

run "environment_must_be_demo_or_prod" {
  command = plan

  variables {
    environment = "staging"
  }

  expect_failures = [var.environment]
}

run "ai_mode_must_be_known" {
  command = plan

  variables {
    ai_mode = "fast"
  }

  expect_failures = [var.ai_mode]
}

run "image_uri_must_not_be_empty" {
  command = plan

  variables {
    image_uri = ""
  }

  expect_failures = [var.image_uri]
}

run "password_version_must_be_positive" {
  command = plan

  variables {
    database_password_version = 0
  }

  expect_failures = [var.database_password_version]
}
