mock_provider "aws" {}

override_resource {
  target = aws_ssm_parameter.secret["anthropic-api-key"]
  values = {
    arn = "arn:aws:ssm:ap-southeast-2:123456789012:parameter/nursing-ai/demo/anthropic-api-key"
  }
}

override_resource {
  target = aws_ssm_parameter.secret["google-client-id"]
  values = {
    arn = "arn:aws:ssm:ap-southeast-2:123456789012:parameter/nursing-ai/demo/google-client-id"
  }
}

override_resource {
  target = aws_ssm_parameter.secret["google-client-secret"]
  values = {
    arn = "arn:aws:ssm:ap-southeast-2:123456789012:parameter/nursing-ai/demo/google-client-secret"
  }
}

override_resource {
  target = aws_cloudwatch_log_group.api
  values = {
    arn = "arn:aws:logs:ap-southeast-2:123456789012:log-group:/aws/lambda/api-fn"
  }
}

override_resource {
  target = aws_cloudwatch_log_group.worker
  values = {
    arn = "arn:aws:logs:ap-southeast-2:123456789012:log-group:/aws/lambda/worker-fn"
  }
}

override_resource {
  target = aws_cloudwatch_log_group.ops
  values = {
    arn = "arn:aws:logs:ap-southeast-2:123456789012:log-group:/aws/lambda/ops-fn"
  }
}

override_resource {
  target = aws_ssm_parameter.site_url
  values = {
    arn = "arn:aws:ssm:ap-southeast-2:123456789012:parameter/nursing-ai/demo/site-url"
  }
}

override_resource {
  target = aws_ssm_parameter.bootstrap_admin_email
  values = {
    arn = "arn:aws:ssm:ap-southeast-2:123456789012:parameter/nursing-ai/demo/bootstrap-admin-email"
  }
}

override_resource {
  target = aws_cloudwatch_log_group.api_access
  values = {
    arn = "arn:aws:logs:ap-southeast-2:123456789012:log-group:/aws/apigateway/access"
  }
}

override_resource {
  target = aws_sns_topic.alarms
  values = {
    arn = "arn:aws:sns:ap-southeast-2:123456789012:alarm-topic"
  }
}

variables {
  name                 = "nursing-ai-demo"
  parameter_path       = "/nursing-ai/demo"
  alarm_email          = "ops@example.com"
  api_function_name    = "nursing-ai-demo-api"
  worker_function_name = "nursing-ai-demo-worker"
  ops_function_name    = "nursing-ai-demo-ops"
  site_url             = "https://d111111abcdef8.cloudfront.net"
  http_api_id          = "abc123"
  dlq_name             = "nursing-ai-demo-dlq"
}

run "logs_kept_14_days" {
  command = plan

  assert {
    condition     = aws_cloudwatch_log_group.api.name == "/aws/lambda/nursing-ai-demo-api" && aws_cloudwatch_log_group.api.retention_in_days == 14
    error_message = "The API function's log group must be kept 14 days."
  }

  assert {
    condition     = aws_cloudwatch_log_group.worker.name == "/aws/lambda/nursing-ai-demo-worker" && aws_cloudwatch_log_group.worker.retention_in_days == 14
    error_message = "The worker function's log group must be kept 14 days."
  }

  assert {
    condition     = aws_cloudwatch_log_group.api_access.name == "/aws/apigateway/nursing-ai-demo-access" && aws_cloudwatch_log_group.api_access.retention_in_days == 14
    error_message = "The API access log group must be kept 14 days."
  }
}

run "alarms_cover_5xx_dlq_and_ai_spend" {
  assert {
    condition     = aws_cloudwatch_metric_alarm.api_5xx.namespace == "AWS/ApiGateway" && aws_cloudwatch_metric_alarm.api_5xx.metric_name == "5xx" && aws_cloudwatch_metric_alarm.api_5xx.statistic == "Sum" && aws_cloudwatch_metric_alarm.api_5xx.threshold == 5 && aws_cloudwatch_metric_alarm.api_5xx.period == 300 && aws_cloudwatch_metric_alarm.api_5xx.evaluation_periods == 1 && aws_cloudwatch_metric_alarm.api_5xx.comparison_operator == "GreaterThanOrEqualToThreshold"
    error_message = "The 5xx alarm must be Sum >= 5 over 5 minutes."
  }

  assert {
    condition     = aws_cloudwatch_metric_alarm.api_5xx.dimensions == tomap({ ApiId = "abc123", Stage = "$default" })
    error_message = "The 5xx alarm must watch the API and its stage."
  }

  assert {
    condition     = aws_cloudwatch_metric_alarm.dlq_depth.namespace == "AWS/SQS" && aws_cloudwatch_metric_alarm.dlq_depth.metric_name == "ApproximateNumberOfMessagesVisible" && aws_cloudwatch_metric_alarm.dlq_depth.statistic == "Maximum" && aws_cloudwatch_metric_alarm.dlq_depth.threshold == 1 && aws_cloudwatch_metric_alarm.dlq_depth.period == 300 && aws_cloudwatch_metric_alarm.dlq_depth.evaluation_periods == 1 && aws_cloudwatch_metric_alarm.dlq_depth.comparison_operator == "GreaterThanOrEqualToThreshold"
    error_message = "The dead-job alarm must be Maximum >= 1 over 5 minutes."
  }

  assert {
    condition     = aws_cloudwatch_metric_alarm.dlq_depth.dimensions == tomap({ QueueName = "nursing-ai-demo-dlq" })
    error_message = "The dead-job alarm must watch the dead-letter queue."
  }

  assert {
    condition     = aws_cloudwatch_metric_alarm.ai_spend.namespace == "NursingAI" && aws_cloudwatch_metric_alarm.ai_spend.metric_name == "AiSpendUsd" && aws_cloudwatch_metric_alarm.ai_spend.statistic == "Sum" && aws_cloudwatch_metric_alarm.ai_spend.threshold == 1 && aws_cloudwatch_metric_alarm.ai_spend.period == 86400 && aws_cloudwatch_metric_alarm.ai_spend.evaluation_periods == 1 && aws_cloudwatch_metric_alarm.ai_spend.comparison_operator == "GreaterThanOrEqualToThreshold"
    error_message = "The AI spend alarm must be Sum >= 1 over a day."
  }

  assert {
    condition     = aws_cloudwatch_metric_alarm.ai_spend.dimensions == null
    error_message = "The AI spend metric has no dimensions."
  }

  assert {
    condition     = alltrue([for a in [aws_cloudwatch_metric_alarm.api_5xx, aws_cloudwatch_metric_alarm.dlq_depth, aws_cloudwatch_metric_alarm.ai_spend] : a.treat_missing_data == "notBreaching"])
    error_message = "Missing data must not count as breaching."
  }

  assert {
    condition     = alltrue([for a in [aws_cloudwatch_metric_alarm.api_5xx, aws_cloudwatch_metric_alarm.dlq_depth, aws_cloudwatch_metric_alarm.ai_spend] : length(a.alarm_actions) == 1 && one(a.alarm_actions) == "arn:aws:sns:ap-southeast-2:123456789012:alarm-topic" && length(a.ok_actions) == 1 && one(a.ok_actions) == "arn:aws:sns:ap-southeast-2:123456789012:alarm-topic"])
    error_message = "Every alarm must notify the topic on alarm and on recovery."
  }
}

run "subscription_and_topic_output" {
  assert {
    condition     = aws_sns_topic_subscription.email.topic_arn == "arn:aws:sns:ap-southeast-2:123456789012:alarm-topic" && aws_sns_topic_subscription.email.protocol == "email" && aws_sns_topic_subscription.email.endpoint == "ops@example.com"
    error_message = "The email subscription must attach to the topic."
  }

  assert {
    condition     = output.alarm_topic_arn == "arn:aws:sns:ap-southeast-2:123456789012:alarm-topic"
    error_message = "alarm_topic_arn must be the topic."
  }
}

run "secrets_never_in_state" {
  command = plan

  assert {
    condition     = length(aws_ssm_parameter.secret) == 3
    error_message = "There must be three parameters."
  }

  assert {
    condition     = alltrue([for k, p in aws_ssm_parameter.secret : p.type == "SecureString" && p.value_wo_version == 1 && p.name == "/nursing-ai/demo/${k}"])
    error_message = "Each parameter must be a SecureString under the path, with a write-only placeholder."
  }

  assert {
    condition     = toset(keys(aws_ssm_parameter.secret)) == toset(["anthropic-api-key", "google-client-id", "google-client-secret"])
    error_message = "The three keys must be anthropic-api-key, google-client-id and google-client-secret."
  }
}

run "outputs_line_up_resource_by_resource" {
  assert {
    condition = output.parameter_arns == {
      "anthropic-api-key"    = "arn:aws:ssm:ap-southeast-2:123456789012:parameter/nursing-ai/demo/anthropic-api-key"
      "google-client-id"     = "arn:aws:ssm:ap-southeast-2:123456789012:parameter/nursing-ai/demo/google-client-id"
      "google-client-secret" = "arn:aws:ssm:ap-southeast-2:123456789012:parameter/nursing-ai/demo/google-client-secret"
    }
    error_message = "parameter_arns must map each key to its own parameter."
  }

  assert {
    condition = output.parameter_names == {
      "anthropic-api-key"    = "/nursing-ai/demo/anthropic-api-key"
      "google-client-id"     = "/nursing-ai/demo/google-client-id"
      "google-client-secret" = "/nursing-ai/demo/google-client-secret"
    }
    error_message = "parameter_names must map each key to its own name."
  }

  assert {
    condition     = output.api_log_group_name == "/aws/lambda/nursing-ai-demo-api" && output.worker_log_group_name == "/aws/lambda/nursing-ai-demo-worker" && output.api_access_log_group_name == "/aws/apigateway/nursing-ai-demo-access"
    error_message = "The log group name outputs must each be their own group."
  }

  assert {
    condition     = output.api_access_log_group_arn == "arn:aws:logs:ap-southeast-2:123456789012:log-group:/aws/apigateway/access"
    error_message = "api_access_log_group_arn must be the access log group's ARN, not another group's."
  }
}

run "bad_parameter_path_is_refused" {
  command = plan

  variables {
    parameter_path = "nursing-ai/demo/"
  }

  expect_failures = [var.parameter_path]
}

run "bad_retention_is_refused" {
  command = plan

  variables {
    log_retention_days = 10
  }

  expect_failures = [var.log_retention_days]
}

run "bad_email_is_refused" {
  command = plan

  variables {
    alarm_email = "nobody"
  }

  expect_failures = [var.alarm_email]
}

run "trailing_slash_path_is_refused" {
  command = plan

  variables {
    parameter_path = "/nursing-ai/demo/"
  }

  expect_failures = [var.parameter_path]
}

run "path_without_leading_slash_is_refused" {
  command = plan

  variables {
    parameter_path = "nursing-ai/demo"
  }

  expect_failures = [var.parameter_path]
}

run "zero_spend_alarm_level_is_refused" {
  command = plan

  variables {
    ai_daily_spend_alarm_usd = 0
  }

  expect_failures = [var.ai_daily_spend_alarm_usd]
}

run "inputs_reach_their_resources" {
  command = plan

  variables {
    log_retention_days        = 30
    ai_daily_spend_alarm_usd  = 2.5
    http_api_stage            = "live"
    ai_spend_metric_namespace = "OtherSpace"
    ai_spend_metric_name      = "OtherMetric"
  }

  assert {
    condition     = aws_cloudwatch_log_group.api.retention_in_days == 30 && aws_cloudwatch_log_group.worker.retention_in_days == 30 && aws_cloudwatch_log_group.api_access.retention_in_days == 30
    error_message = "log_retention_days must reach all three log groups."
  }

  assert {
    condition     = aws_cloudwatch_metric_alarm.ai_spend.threshold == 2.5 && aws_cloudwatch_metric_alarm.ai_spend.namespace == "OtherSpace" && aws_cloudwatch_metric_alarm.ai_spend.metric_name == "OtherMetric"
    error_message = "The AI spend settings must reach the AI spend alarm."
  }

  assert {
    condition     = aws_cloudwatch_metric_alarm.api_5xx.dimensions["Stage"] == "live"
    error_message = "http_api_stage must reach the 5xx alarm."
  }
}

run "ops_function_logs_kept_14_days" {
  command = plan

  assert {
    condition     = aws_cloudwatch_log_group.ops.name == "/aws/lambda/nursing-ai-demo-ops" && aws_cloudwatch_log_group.ops.retention_in_days == 14
    error_message = "The ops function's log group must be kept 14 days."
  }
  assert {
    condition     = output.ops_log_group_name == "/aws/lambda/nursing-ai-demo-ops"
    error_message = "ops_log_group_name must be the ops function's group."
  }
}

run "site_url_parameter_is_a_plain_string" {
  command = plan

  assert {
    condition     = aws_ssm_parameter.site_url.name == "/nursing-ai/demo/site-url" && aws_ssm_parameter.site_url.type == "String"
    error_message = "The site address is a plain String under the path: it is public and Terraform writes it."
  }
  assert {
    condition     = aws_ssm_parameter.site_url.value == "https://d111111abcdef8.cloudfront.net"
    error_message = "The site-url parameter must hold the address it was given."
  }
  assert {
    condition     = output.site_url_parameter_name == "/nursing-ai/demo/site-url"
    error_message = "site_url_parameter_name must name the parameter."
  }
}

run "site_url_must_be_an_origin" {
  command = plan

  variables {
    site_url = "https://d111111abcdef8.cloudfront.net/"
  }

  expect_failures = [var.site_url]
}

run "site_url_must_be_https_or_http" {
  command = plan

  variables {
    site_url = "d111111abcdef8.cloudfront.net"
  }

  expect_failures = [var.site_url]
}

run "bootstrap_admin_email_is_set_by_hand" {
  command = plan

  assert {
    condition     = aws_ssm_parameter.bootstrap_admin_email.name == "/nursing-ai/demo/bootstrap-admin-email" && aws_ssm_parameter.bootstrap_admin_email.type == "SecureString"
    error_message = "The bootstrap admin email is a SecureString under the path."
  }
  assert {
    condition     = aws_ssm_parameter.bootstrap_admin_email.value_wo_version == 1
    error_message = "The placeholder must go in as a write-only value, version 1."
  }
}

run "new_parameter_outputs_line_up" {
  assert {
    condition     = output.site_url_parameter_arn == "arn:aws:ssm:ap-southeast-2:123456789012:parameter/nursing-ai/demo/site-url" && output.bootstrap_admin_email_parameter_arn == "arn:aws:ssm:ap-southeast-2:123456789012:parameter/nursing-ai/demo/bootstrap-admin-email"
    error_message = "each ARN output must be its own parameter's."
  }
  assert {
    condition     = output.bootstrap_admin_email_parameter_name == "/nursing-ai/demo/bootstrap-admin-email"
    error_message = "bootstrap_admin_email_parameter_name must name the parameter."
  }
  assert {
    condition     = output.alarm_names == { api_5xx = "nursing-ai-demo-api-5xx", dead_jobs = "nursing-ai-demo-dead-jobs", ai_spend = "nursing-ai-demo-ai-spend" }
    error_message = "alarm_names must name the 5xx, dead-letter and AI-spend alarms."
  }
}

run "placeholder_email_must_have_exactly_one_at_sign" {
  command = plan

  variables {
    bootstrap_admin_email_placeholder = "nobody@@example.com"
  }

  expect_failures = [var.bootstrap_admin_email_placeholder]
}

run "placeholder_email_without_an_at_sign_is_refused" {
  command = plan

  variables {
    bootstrap_admin_email_placeholder = "nobody"
  }

  expect_failures = [var.bootstrap_admin_email_placeholder]
}

run "placeholder_email_defaults_to_an_example_address" {
  command = plan

  assert {
    condition     = var.bootstrap_admin_email_placeholder == "nobody@example.com"
    error_message = "The default placeholder is nobody@example.com."
  }
}
