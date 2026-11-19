mock_provider "aws" {
  mock_resource "aws_sqs_queue" {
    defaults = {
      arn = "arn:aws:sqs:ap-southeast-2:123456789012:mock-queue"
      url = "https://sqs.ap-southeast-2.amazonaws.com/123456789012/mock-queue"
    }
  }

  mock_resource "aws_iam_role" {
    defaults = {
      arn = "arn:aws:iam::123456789012:role/mock-role"
    }
  }

  mock_resource "aws_apigatewayv2_api" {
    defaults = {
      execution_arn = "arn:aws:execute-api:ap-southeast-2:123456789012:mockapi"
    }
  }

  mock_resource "aws_lambda_function" {
    defaults = {
      arn        = "arn:aws:lambda:ap-southeast-2:123456789012:function:mock"
      invoke_arn = "arn:aws:apigateway:ap-southeast-2:lambda:path/2015-03-31/functions/arn:aws:lambda:ap-southeast-2:123456789012:function:mock/invocations"
    }
  }
}

override_resource {
  target = aws_sqs_queue.jobs
  values = {
    arn = "arn:aws:sqs:ap-southeast-2:123456789012:jobs-queue"
    url = "https://sqs.ap-southeast-2.amazonaws.com/123456789012/jobs-queue"
  }
}

override_resource {
  target = aws_sqs_queue.dlq
  values = {
    arn = "arn:aws:sqs:ap-southeast-2:123456789012:dead-letter-queue"
    url = "https://sqs.ap-southeast-2.amazonaws.com/123456789012/dead-letter-queue"
  }
}

override_resource {
  target = aws_iam_role.api
  values = {
    arn = "arn:aws:iam::123456789012:role/api-role"
  }
}

override_resource {
  target = aws_iam_role.worker
  values = {
    arn = "arn:aws:iam::123456789012:role/worker-role"
  }
}

override_resource {
  target = aws_iam_role.ops
  values = {
    arn = "arn:aws:iam::123456789012:role/ops-role"
  }
}

override_resource {
  target = aws_lambda_function.api
  values = {
    arn        = "arn:aws:lambda:ap-southeast-2:123456789012:function:api-function"
    invoke_arn = "arn:aws:apigateway:ap-southeast-2:lambda:path/2015-03-31/functions/api-function/invocations"
  }
}

override_resource {
  target = aws_lambda_function.worker
  values = {
    arn        = "arn:aws:lambda:ap-southeast-2:123456789012:function:worker-function"
    invoke_arn = "arn:aws:apigateway:ap-southeast-2:lambda:path/2015-03-31/functions/worker-function/invocations"
  }
}

variables {
  site_url_parameter_arn               = "arn:aws:ssm:ap-southeast-2:123456789012:parameter/nursing-ai/test/site-url"
  site_url_parameter_name              = "/nursing-ai/test/site-url"
  bootstrap_admin_email_parameter_arn  = "arn:aws:ssm:ap-southeast-2:123456789012:parameter/nursing-ai/test/bootstrap-admin-email"
  bootstrap_admin_email_parameter_name = "/nursing-ai/test/bootstrap-admin-email"
  ops_log_group_name                   = "/aws/lambda/nursing-ai-test-ops"
  name                                 = "nursing-ai-test"
  image_uri                            = "123456789012.dkr.ecr.ap-southeast-2.amazonaws.com/nursing-ai-test:abc123"
  subnet_ids                           = ["subnet-aaa", "subnet-bbb"]
  security_group_ids                   = ["sg-111"]
  database_url_parameter_arn           = "arn:aws:ssm:ap-southeast-2:123456789012:parameter/nursing-ai/test/database-url"
  database_url_parameter_name          = "/nursing-ai/test/database-url"
  anthropic_api_key_parameter_arn      = "arn:aws:ssm:ap-southeast-2:123456789012:parameter/nursing-ai/test/anthropic-api-key"
  anthropic_api_key_parameter_name     = "/nursing-ai/test/anthropic-api-key"
  google_client_id_parameter_arn       = "arn:aws:ssm:ap-southeast-2:123456789012:parameter/nursing-ai/test/google-client-id"
  google_client_id_parameter_name      = "/nursing-ai/test/google-client-id"
  google_client_secret_parameter_arn   = "arn:aws:ssm:ap-southeast-2:123456789012:parameter/nursing-ai/test/google-client-secret"
  google_client_secret_parameter_name  = "/nursing-ai/test/google-client-secret"
  api_log_group_name                   = "/aws/lambda/nursing-ai-test-api"
  worker_log_group_name                = "/aws/lambda/nursing-ai-test-worker"
  api_access_log_group_arn             = "arn:aws:logs:ap-southeast-2:123456789012:log-group:/aws/apigateway/nursing-ai-test"
}

run "worker_batch_size_is_one" {
  command = plan

  assert {
    condition     = aws_lambda_event_source_mapping.worker.batch_size == 1
    error_message = "the worker must take one job at a time"
  }
  assert {
    condition     = aws_lambda_event_source_mapping.worker.scaling_config[0].maximum_concurrency == 2
    error_message = "the worker's maximum concurrency must default to 2"
  }
}

run "dlq_attached" {
  command = apply

  assert {
    condition     = jsondecode(aws_sqs_queue.jobs.redrive_policy).deadLetterTargetArn == aws_sqs_queue.dlq.arn
    error_message = "the redrive policy must point at the DLQ"
  }
  assert {
    condition     = jsondecode(aws_sqs_queue.jobs.redrive_policy).maxReceiveCount == 5
    error_message = "a job must move to the DLQ after 5 receives"
  }
  assert {
    condition     = aws_sqs_queue.jobs.visibility_timeout_seconds == 720
    error_message = "the visibility timeout must be 6 times the worker timeout (720 s)"
  }
  assert {
    condition     = aws_sqs_queue.dlq.message_retention_seconds == 1209600
    error_message = "the DLQ must keep messages for 14 days"
  }
  assert {
    condition     = aws_sqs_queue.jobs.name == "nursing-ai-test-draft-jobs" && aws_sqs_queue.dlq.name == "nursing-ai-test-draft-jobs-dlq"
    error_message = "queue names come from var.name"
  }
  assert {
    condition     = aws_sqs_queue.jobs.sqs_managed_sse_enabled == true && aws_sqs_queue.dlq.sqs_managed_sse_enabled == true
    error_message = "both queues must be encrypted"
  }
  assert {
    condition     = jsondecode(aws_sqs_queue_redrive_allow_policy.dlq.redrive_allow_policy).redrivePermission == "byQueue"
    error_message = "only named queues may redrive into the DLQ"
  }
  assert {
    condition     = jsondecode(aws_sqs_queue_redrive_allow_policy.dlq.redrive_allow_policy).sourceQueueArns == [aws_sqs_queue.jobs.arn]
    error_message = "only the jobs queue may redrive into the DLQ"
  }
}

run "api_throttled" {
  command = plan

  assert {
    condition     = aws_apigatewayv2_stage.default.default_route_settings[0].throttling_rate_limit == 10
    error_message = "the stage rate must be 10 requests a second"
  }
  assert {
    condition     = aws_apigatewayv2_stage.default.default_route_settings[0].throttling_burst_limit == 20
    error_message = "the stage burst must be 20"
  }
  assert {
    condition     = length(aws_apigatewayv2_stage.default.access_log_settings) == 1
    error_message = "access logging must be on"
  }
  assert {
    condition     = aws_apigatewayv2_stage.default.name == "$default" && aws_apigatewayv2_stage.default.auto_deploy == true
    error_message = "the stage is $default with auto deploy"
  }
  assert {
    condition     = aws_apigatewayv2_route.default.route_key == "$default"
    error_message = "one catch-all route"
  }
  assert {
    condition     = aws_apigatewayv2_integration.api.payload_format_version == "2.0" && aws_apigatewayv2_integration.api.integration_type == "AWS_PROXY"
    error_message = "the integration must be a version 2.0 proxy"
  }
  assert {
    condition     = toset(keys(jsondecode(aws_apigatewayv2_stage.default.access_log_settings[0].format))) == toset(["requestId", "ip", "requestTime", "httpMethod", "routeKey", "status", "responseLength", "integrationLatency"])
    error_message = "the access log must carry exactly the listed metadata fields"
  }
  assert {
    condition     = aws_lambda_function.api.timeout == 29
    error_message = "the API timeout must fit inside the HTTP API's 30 s limit"
  }
}

run "environment_uses_the_settings_names" {
  command = plan

  assert {
    condition     = alltrue([for k in ["APP_ENV", "AI_MODE", "DATABASE_URL_SSM_PARAMETER"] : contains(keys(aws_lambda_function.api.environment[0].variables), k) && contains(keys(aws_lambda_function.worker.environment[0].variables), k)])
    error_message = "both functions need APP_ENV, AI_MODE and DATABASE_URL_SSM_PARAMETER"
  }
  assert {
    condition     = alltrue([for k in ["DATABASE_URL", "ANTHROPIC_API_KEY", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"] : !contains(keys(aws_lambda_function.api.environment[0].variables), k) && !contains(keys(aws_lambda_function.worker.environment[0].variables), k)])
    error_message = "no secret value may be a plain environment variable"
  }
  assert {
    condition     = !contains(keys(aws_lambda_function.api.environment[0].variables), "AI_MONTHLY_CAP_USD") && !contains(keys(aws_lambda_function.worker.environment[0].variables), "AI_MONTHLY_CAP_USD")
    error_message = "AI_MONTHLY_CAP_USD must be absent while the cap is null"
  }
  assert {
    condition     = aws_lambda_function.api.environment[0].variables["DATABASE_URL_SSM_PARAMETER"] == "/nursing-ai/test/database-url"
    error_message = "the database parameter name is passed through"
  }
  assert {
    condition     = aws_lambda_function.api.environment[0].variables["GOOGLE_CLIENT_ID_SSM_PARAMETER"] == "/nursing-ai/test/google-client-id" && aws_lambda_function.api.environment[0].variables["GOOGLE_CLIENT_SECRET_SSM_PARAMETER"] == "/nursing-ai/test/google-client-secret"
    error_message = "the API gets the Google parameter names"
  }
  assert {
    condition     = aws_lambda_function.worker.environment[0].variables["ANTHROPIC_API_KEY_SSM_PARAMETER"] == "/nursing-ai/test/anthropic-api-key" && !contains(keys(aws_lambda_function.api.environment[0].variables), "ANTHROPIC_API_KEY_SSM_PARAMETER")
    error_message = "only the worker gets the Anthropic parameter name"
  }
}

run "cap_appears_only_when_set" {
  command = plan

  variables {
    ai_monthly_cap_usd = 25
  }

  assert {
    condition     = aws_lambda_function.api.environment[0].variables["AI_MONTHLY_CAP_USD"] == "25" && aws_lambda_function.worker.environment[0].variables["AI_MONTHLY_CAP_USD"] == "25"
    error_message = "the cap must reach both functions as a string"
  }
}

run "only_the_worker_reads_the_anthropic_key" {
  command = plan

  assert {
    condition     = contains(flatten([for s in jsondecode(aws_iam_role_policy.worker.policy).Statement : s.Resource]), var.anthropic_api_key_parameter_arn)
    error_message = "the worker policy must name the Anthropic parameter"
  }
  assert {
    condition     = !contains(flatten([for s in jsondecode(aws_iam_role_policy.api.policy).Statement : s.Resource]), var.anthropic_api_key_parameter_arn)
    error_message = "the API policy must not name the Anthropic parameter"
  }
  assert {
    condition     = contains(flatten([for s in jsondecode(aws_iam_role_policy.api.policy).Statement : s.Action]), "sqs:SendMessage")
    error_message = "the API must be able to send jobs"
  }
  assert {
    condition     = !contains(flatten([for s in jsondecode(aws_iam_role_policy.worker.policy).Statement : s.Action]), "sqs:SendMessage")
    error_message = "the worker must not send jobs"
  }
  assert {
    condition     = contains(flatten([for s in jsondecode(aws_iam_role_policy.api.policy).Statement : s.Resource]), var.google_client_id_parameter_arn) && contains(flatten([for s in jsondecode(aws_iam_role_policy.api.policy).Statement : s.Resource]), var.google_client_secret_parameter_arn)
    error_message = "the API reads the Google parameters"
  }
  assert {
    condition     = !contains(flatten([for s in jsondecode(aws_iam_role_policy.worker.policy).Statement : s.Resource]), var.google_client_id_parameter_arn)
    error_message = "the worker must not read the Google parameters"
  }
  assert {
    condition     = alltrue([for p in [aws_iam_role_policy.api.policy, aws_iam_role_policy.worker.policy] : alltrue([for s in jsondecode(p).Statement : !contains(flatten([s.Resource]), "*")])])
    error_message = "no inline policy may use a * resource"
  }
}

run "lambdas_use_ipv6_and_the_web_adapter" {
  command = plan

  assert {
    condition     = aws_lambda_function.api.vpc_config[0].ipv6_allowed_for_dual_stack == true && aws_lambda_function.worker.vpc_config[0].ipv6_allowed_for_dual_stack == true
    error_message = "both functions must allow IPv6 in the dual-stack subnets"
  }
  assert {
    condition     = aws_lambda_function.worker.environment[0].variables["AWS_LWA_PASS_THROUGH_PATH"] == "/events" && aws_lambda_function.worker.environment[0].variables["APP_ROLE"] == "worker"
    error_message = "the worker must pass queue events through to /events"
  }
  assert {
    condition     = aws_lambda_function.worker.environment[0].variables["AWS_LWA_ERROR_STATUS_CODES"] == "500-599"
    error_message = "the worker must make the adapter fail the invocation on a 5xx, or SQS deletes a message whose job was not finished"
  }
  assert {
    condition     = !contains(keys(aws_lambda_function.api.environment[0].variables), "AWS_LWA_ERROR_STATUS_CODES") && !contains(keys(aws_lambda_function.ops.environment[0].variables), "AWS_LWA_ERROR_STATUS_CODES")
    error_message = "the API (its 5xx must reach the browser) and ops (the deploy reads its 500 body) must not turn a 5xx into a Lambda error"
  }
  assert {
    condition     = aws_lambda_function.api.environment[0].variables["APP_ROLE"] == "api" && !contains(keys(aws_lambda_function.api.environment[0].variables), "AWS_LWA_PASS_THROUGH_PATH")
    error_message = "the API role is api and has no pass-through path"
  }
  assert {
    condition     = aws_lambda_function.api.environment[0].variables["AWS_LWA_READINESS_CHECK_PROTOCOL"] == "tcp" && aws_lambda_function.api.environment[0].variables["AWS_LWA_PORT"] == "8080"
    error_message = "readiness is a TCP check on 8080"
  }
  assert {
    condition     = aws_lambda_function.worker.environment[0].variables["AWS_LWA_READINESS_CHECK_PROTOCOL"] == "tcp" && aws_lambda_function.worker.environment[0].variables["AWS_LWA_PORT"] == "8080"
    error_message = "the worker's readiness is a TCP check on 8080"
  }
  assert {
    condition     = aws_lambda_function.api.package_type == "Image" && aws_lambda_function.worker.package_type == "Image"
    error_message = "both functions run the container image"
  }
}

run "wiring_points_each_resource_at_the_right_one" {
  command = apply

  assert {
    condition     = aws_sqs_queue.jobs.arn != aws_sqs_queue.dlq.arn && aws_iam_role.api.arn != aws_iam_role.worker.arn && aws_lambda_function.api.arn != aws_lambda_function.worker.arn
    error_message = "the test's mock ARNs must be distinct or the wiring checks mean nothing"
  }
  assert {
    condition     = jsondecode(aws_sqs_queue_redrive_allow_policy.dlq.redrive_allow_policy).sourceQueueArns == ["arn:aws:sqs:ap-southeast-2:123456789012:jobs-queue"]
    error_message = "only the jobs queue may redrive into the DLQ"
  }
  assert {
    condition     = jsondecode(aws_sqs_queue.jobs.redrive_policy).deadLetterTargetArn == "arn:aws:sqs:ap-southeast-2:123456789012:dead-letter-queue"
    error_message = "the jobs queue must redrive into the DLQ"
  }
  assert {
    condition     = alltrue([for s in jsondecode(aws_iam_role_policy.worker.policy).Statement : s.Resource == aws_sqs_queue.jobs.arn if contains(flatten([s.Action]), "sqs:ReceiveMessage")])
    error_message = "the worker reads the jobs queue"
  }
  assert {
    condition     = length([for s in jsondecode(aws_iam_role_policy.worker.policy).Statement : s if s.Resource == aws_sqs_queue.jobs.arn && contains(flatten([s.Action]), "sqs:ReceiveMessage")]) == 1
    error_message = "the worker policy must grant ReceiveMessage on the jobs queue"
  }
  assert {
    condition     = length([for s in jsondecode(aws_iam_role_policy.api.policy).Statement : s if s.Resource == aws_sqs_queue.jobs.arn && contains(flatten([s.Action]), "sqs:SendMessage")]) == 1
    error_message = "the API policy must grant SendMessage on the jobs queue"
  }
  assert {
    condition     = aws_lambda_event_source_mapping.worker.event_source_arn == aws_sqs_queue.jobs.arn
    error_message = "the worker must be fed from the jobs queue"
  }
  assert {
    condition     = aws_lambda_event_source_mapping.worker.function_name == aws_lambda_function.worker.arn
    error_message = "the queue must feed the worker function"
  }
  assert {
    condition     = aws_apigatewayv2_integration.api.integration_uri == aws_lambda_function.api.invoke_arn
    error_message = "the HTTP API must call the API function"
  }
  assert {
    condition     = aws_apigatewayv2_integration.api.integration_method == "POST"
    error_message = "the integration must use POST"
  }
  assert {
    condition     = aws_lambda_function.api.role == aws_iam_role.api.arn && aws_lambda_function.worker.role == aws_iam_role.worker.arn
    error_message = "each function must run as its own role"
  }
  assert {
    condition     = aws_lambda_function.api.environment[0].variables["DRAFT_QUEUE_URL"] == aws_sqs_queue.jobs.url
    error_message = "the API must send to the jobs queue"
  }
  assert {
    condition     = aws_lambda_permission.api_gateway.function_name == aws_lambda_function.api.function_name
    error_message = "the HTTP API may invoke only the API function"
  }
}

run "swapped_parameter_arn_and_name_is_refused" {
  command = plan

  variables {
    database_url_parameter_arn  = "/nursing-ai/test/database-url"
    database_url_parameter_name = "arn:aws:ssm:ap-southeast-2:123456789012:parameter/nursing-ai/test/database-url"
  }

  # The name is refused for not starting with /. The ARN's own checks are not
  # reported then: the ARN is checked against the name, which is invalid.
  expect_failures = [
    var.database_url_parameter_name,
  ]
}

# Each ARN's shape rule alone: the value is not an ARN, but it still ends with
# :parameter<name>, so the name rule passes and only the shape rule can fail.
run "database_url_parameter_arn_must_be_an_arn" {
  command = plan

  variables {
    database_url_parameter_arn = "not-an-arn:parameter/nursing-ai/test/database-url"
  }

  expect_failures = [var.database_url_parameter_arn]
}

run "anthropic_api_key_parameter_arn_must_be_an_arn" {
  command = plan

  variables {
    anthropic_api_key_parameter_arn = "not-an-arn:parameter/nursing-ai/test/anthropic-api-key"
  }

  expect_failures = [var.anthropic_api_key_parameter_arn]
}

run "google_client_id_parameter_arn_must_be_an_arn" {
  command = plan

  variables {
    google_client_id_parameter_arn = "not-an-arn:parameter/nursing-ai/test/google-client-id"
  }

  expect_failures = [var.google_client_id_parameter_arn]
}

run "google_client_secret_parameter_arn_must_be_an_arn" {
  command = plan

  variables {
    google_client_secret_parameter_arn = "not-an-arn:parameter/nursing-ai/test/google-client-secret"
  }

  expect_failures = [var.google_client_secret_parameter_arn]
}

run "site_url_parameter_arn_must_be_an_arn" {
  command = plan

  variables {
    site_url_parameter_arn = "not-an-arn:parameter/nursing-ai/test/site-url"
  }

  expect_failures = [var.site_url_parameter_arn]
}

run "bootstrap_admin_email_parameter_arn_must_be_an_arn" {
  command = plan

  variables {
    bootstrap_admin_email_parameter_arn = "not-an-arn:parameter/nursing-ai/test/bootstrap-admin-email"
  }

  expect_failures = [var.bootstrap_admin_email_parameter_arn]
}

run "log_groups_are_exposed_by_function" {
  command = plan

  assert {
    condition     = output.function_log_groups == { api = "/aws/lambda/nursing-ai-test-api", worker = "/aws/lambda/nursing-ai-test-worker", ops = "/aws/lambda/nursing-ai-test-ops" }
    error_message = "function_log_groups must give each function's own log group."
  }
}

# Each ARN's name rule alone: a well-formed SSM ARN of a different parameter.
run "database_url_parameter_arn_must_match_its_name" {
  command = plan

  variables {
    database_url_parameter_arn = "arn:aws:ssm:ap-southeast-2:123456789012:parameter/nursing-ai/test/site-url"
  }

  expect_failures = [var.database_url_parameter_arn]
}

run "parameter_arn_must_match_its_name" {
  command = plan

  variables {
    anthropic_api_key_parameter_arn = "arn:aws:ssm:ap-southeast-2:123456789012:parameter/nursing-ai/test/google-client-id"
  }

  expect_failures = [var.anthropic_api_key_parameter_arn]
}

run "google_client_id_parameter_arn_must_match_its_name" {
  command = plan

  variables {
    google_client_id_parameter_arn = "arn:aws:ssm:ap-southeast-2:123456789012:parameter/nursing-ai/test/google-client-secret"
  }

  expect_failures = [var.google_client_id_parameter_arn]
}

run "google_client_secret_parameter_arn_must_match_its_name" {
  command = plan

  variables {
    google_client_secret_parameter_arn = "arn:aws:ssm:ap-southeast-2:123456789012:parameter/nursing-ai/test/google-client-id"
  }

  expect_failures = [var.google_client_secret_parameter_arn]
}

run "site_url_parameter_arn_must_match_its_name" {
  command = plan

  variables {
    site_url_parameter_arn = "arn:aws:ssm:ap-southeast-2:123456789012:parameter/nursing-ai/test/database-url"
  }

  expect_failures = [var.site_url_parameter_arn]
}

run "bootstrap_admin_email_parameter_arn_must_match_its_name" {
  command = plan

  variables {
    bootstrap_admin_email_parameter_arn = "arn:aws:ssm:ap-southeast-2:123456789012:parameter/nursing-ai/test/site-url"
  }

  expect_failures = [var.bootstrap_admin_email_parameter_arn]
}

run "ops_function_runs_tasks_only" {
  command = plan

  assert {
    condition     = aws_lambda_function.ops.function_name == "nursing-ai-test-ops" && aws_lambda_function.ops.image_uri == aws_lambda_function.api.image_uri && aws_lambda_function.ops.package_type == "Image"
    error_message = "the ops function runs the same image as the others"
  }
  assert {
    condition     = aws_lambda_function.ops.environment[0].variables["APP_ROLE"] == "ops" && aws_lambda_function.ops.environment[0].variables["AWS_LWA_PASS_THROUGH_PATH"] == "/events"
    error_message = "the ops function is the ops role and takes its tasks on /events"
  }
  assert {
    condition     = aws_lambda_function.ops.timeout == 300
    error_message = "a migration may take up to 300 s"
  }
  assert {
    condition     = aws_lambda_function.ops.vpc_config[0].ipv6_allowed_for_dual_stack == true && aws_lambda_function.ops.vpc_config[0].subnet_ids == toset(["subnet-aaa", "subnet-bbb"]) && aws_lambda_function.ops.vpc_config[0].security_group_ids == toset(["sg-111"])
    error_message = "the ops function sits in the same VPC subnets and groups, with IPv6"
  }
  assert {
    condition     = aws_lambda_function.ops.logging_config[0].log_group == "/aws/lambda/nursing-ai-test-ops" && output.function_log_groups.ops == "/aws/lambda/nursing-ai-test-ops"
    error_message = "the ops function logs to the group ops made"
  }
  assert {
    condition     = aws_lambda_function.ops.environment[0].variables["DRAFT_QUEUE_URL"] == aws_sqs_queue.jobs.url && aws_lambda_function.ops.environment[0].variables["SITE_URL_SSM_PARAMETER"] == "/nursing-ai/test/site-url"
    error_message = "smoke needs the queue URL and the site-URL parameter name"
  }
  assert {
    condition     = !contains(keys(aws_lambda_function.ops.environment[0].variables), "ANTHROPIC_API_KEY_SSM_PARAMETER") && !contains(keys(aws_lambda_function.ops.environment[0].variables), "GOOGLE_CLIENT_ID_SSM_PARAMETER") && !contains(keys(aws_lambda_function.ops.environment[0].variables), "BOOTSTRAP_ADMIN_EMAIL_SSM_PARAMETER")
    error_message = "the ops function is given none of the other secrets"
  }
  assert {
    condition     = aws_lambda_permission.api_gateway.function_name == aws_lambda_function.api.function_name && aws_lambda_permission.api_gateway.function_name != aws_lambda_function.ops.function_name
    error_message = "only the API function is behind the HTTP API"
  }
  assert {
    condition     = output.ops_function_name == "nursing-ai-test-ops" && output.ops_role_name == aws_iam_role.ops.name
    error_message = "compute must expose the ops function and role names"
  }
}

run "ops_role_reads_only_its_parameters" {
  command = plan

  assert {
    condition     = sort(flatten([for s in jsondecode(aws_iam_role_policy.ops.policy).Statement : s.Resource if contains(flatten([s.Action]), "ssm:GetParameter")])) == sort([var.database_url_parameter_arn, var.site_url_parameter_arn])
    error_message = "the ops role reads the database URL and the site URL, nothing else"
  }
  assert {
    condition     = length([for s in jsondecode(aws_iam_role_policy.ops.policy).Statement : s if contains(flatten([s.Action]), "sqs:GetQueueAttributes") && s.Resource == aws_sqs_queue.jobs.arn]) == 1
    error_message = "the ops role may read the jobs queue's attributes"
  }
  assert {
    condition     = sort(flatten([for s in jsondecode(aws_iam_role_policy.ops.policy).Statement : s.Action])) == sort(["sqs:GetQueueAttributes", "ssm:GetParameter"])
    error_message = "the ops role has no other action"
  }
  assert {
    condition     = alltrue([for s in jsondecode(aws_iam_role_policy.ops.policy).Statement : !contains(flatten([s.Resource]), "*")])
    error_message = "no * resource in the ops policy"
  }
  assert {
    condition     = aws_iam_role_policy_attachment.ops_vpc_access.policy_arn == "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
    error_message = "the ops role attaches to the VPC like the others"
  }
  assert {
    condition     = contains(flatten([for s in jsondecode(aws_iam_role_policy.api.policy).Statement : s.Resource]), var.bootstrap_admin_email_parameter_arn) && contains(flatten([for s in jsondecode(aws_iam_role_policy.api.policy).Statement : s.Resource]), var.site_url_parameter_arn)
    error_message = "the API reads the bootstrap admin email and the site URL"
  }
  assert {
    condition     = !contains(flatten([for s in jsondecode(aws_iam_role_policy.worker.policy).Statement : s.Resource]), var.bootstrap_admin_email_parameter_arn) && contains(flatten([for s in jsondecode(aws_iam_role_policy.worker.policy).Statement : s.Resource]), var.site_url_parameter_arn)
    error_message = "the worker reads the site URL but not the bootstrap admin email"
  }
  assert {
    condition     = !contains(flatten([for s in jsondecode(aws_iam_role_policy.ops.policy).Statement : s.Resource]), var.bootstrap_admin_email_parameter_arn)
    error_message = "the ops role must not read the bootstrap admin email"
  }
}

run "lambdas_use_null_pool_and_a_20_second_connect" {
  command = plan

  assert {
    condition     = alltrue([for f in [aws_lambda_function.api, aws_lambda_function.worker, aws_lambda_function.ops] : f.environment[0].variables["DB_POOL"] == "null" && f.environment[0].variables["DB_CONNECT_TIMEOUT_S"] == "20"])
    error_message = "every function uses no pool and waits 20 s for a pausing database"
  }
  assert {
    condition     = alltrue([for f in [aws_lambda_function.api, aws_lambda_function.worker, aws_lambda_function.ops] : f.environment[0].variables["SITE_URL_SSM_PARAMETER"] == "/nursing-ai/test/site-url"])
    error_message = "every function is given the site-URL parameter name"
  }
}

run "api_gets_the_daily_draft_cap" {
  command = plan

  assert {
    condition     = aws_lambda_function.api.environment[0].variables["AI_DAILY_DRAFTS_PER_USER"] == "20" && aws_lambda_function.api.environment[0].variables["IDLE_LOCK_MINUTES"] == "5"
    error_message = "the API gets the daily draft cap and the idle lock by default"
  }
  assert {
    condition     = aws_lambda_function.api.environment[0].variables["BOOTSTRAP_ADMIN_EMAIL_SSM_PARAMETER"] == "/nursing-ai/test/bootstrap-admin-email"
    error_message = "the API is given the bootstrap admin email parameter name"
  }
  assert {
    condition     = alltrue([for f in [aws_lambda_function.worker, aws_lambda_function.ops] : !contains(keys(f.environment[0].variables), "AI_DAILY_DRAFTS_PER_USER") && !contains(keys(f.environment[0].variables), "IDLE_LOCK_MINUTES") && !contains(keys(f.environment[0].variables), "BOOTSTRAP_ADMIN_EMAIL_SSM_PARAMETER")])
    error_message = "only the API gets these three settings"
  }
}

run "cap_and_idle_lock_follow_their_variables" {
  command = plan

  variables {
    ai_daily_drafts_per_user = 7
    idle_lock_minutes        = 10
  }

  assert {
    condition     = aws_lambda_function.api.environment[0].variables["AI_DAILY_DRAFTS_PER_USER"] == "7" && aws_lambda_function.api.environment[0].variables["IDLE_LOCK_MINUTES"] == "10"
    error_message = "the variables must reach the API as strings"
  }
}

run "daily_cap_must_be_positive" {
  command = plan

  variables {
    ai_daily_drafts_per_user = 0
  }

  expect_failures = [var.ai_daily_drafts_per_user]
}

# The job lease is 150 s (the worker's 120 s plus 30). A longer timeout would let a second run claim
# a job the first is still working on.
run "worker_timeout_may_not_pass_the_lease" {
  command = plan

  variables {
    worker_timeout_s = 121
  }

  expect_failures = [var.worker_timeout_s]
}

run "worker_timeout_of_120_is_allowed" {
  command = plan

  variables {
    worker_timeout_s = 120
  }
}
