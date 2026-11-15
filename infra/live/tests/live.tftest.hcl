# Every module sits under one mocked AWS provider; the random provider is real.
# A mock gives every resource of a type the same computed values, so the
# overrides give each role and parameter its own value (the role overrides sit
# in the runs for the demo environment, since a role's ARN ends with its name).
# A wiring mistake, such as a role's name paired with the other role's ARN,
# then fails instead of passing by construction.
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

# This run goes first: runs share state, and a role's ARN left over from a
# demo run would not match the prod role names.
run "names_follow_a_prod_environment" {
  command = plan

  variables {
    environment = "prod"
  }

  override_resource {
    target = module.compute.aws_iam_role.api
    values = {
      arn = "arn:aws:iam::123456789012:role/nursing-ai-prod-api"
    }
  }

  override_resource {
    target = module.compute.aws_iam_role.worker
    values = {
      arn = "arn:aws:iam::123456789012:role/nursing-ai-prod-worker"
    }
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

  # Apply mode: the roles and parameters carry distinct overrides, and the
  # brake's validation fails unless each role's name matches its own ARN.
  assert {
    condition     = length(module.brake.deny_policy_arn) > 0 && length(module.brake.brake_role_arn) > 0
    error_message = "the brake must be planned with compute's two roles"
  }
  assert {
    condition     = module.compute.api_role_arn != module.compute.worker_role_arn && endswith(module.compute.api_role_arn, ":role/${module.compute.api_role_name}") && endswith(module.compute.worker_role_arn, ":role/${module.compute.worker_role_name}")
    error_message = "each role's name must belong to its own ARN"
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
  assert {
    condition     = length(module.ops.alarm_topic_arn) > 0 && length(module.ops.api_access_log_group_arn) > 0
    error_message = "ops must be planned"
  }
}

run "lambdas_log_to_the_groups_ops_made" {
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

  # Ops makes each log group from the function name the locals gave it; the
  # function itself is named by compute. The two must agree, or the function
  # would write to a group of its own and ignore the one with retention.
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

  # The web module only creates its /api/* behaviour and origin when it is
  # given an API host, and it refuses a host that carries https://. The run
  # passing means the root hands it the bare host from compute's endpoint.
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

run "names_follow_the_environment" {
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
