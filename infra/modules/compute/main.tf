locals {
  # Settings both functions share. Secrets are never values here: the app gets
  # the name of a SecureString and reads it itself at cold start, because an
  # environment variable sits in state and in the console as plain text.
  shared_environment = merge(
    {
      APP_ENV                          = var.app_env
      AI_MODE                          = var.ai_mode
      DATABASE_URL_SSM_PARAMETER       = var.database_url_parameter_name
      AWS_LWA_PORT                     = "8080"
      AWS_LWA_READINESS_CHECK_PROTOCOL = "tcp"
    },
    var.ai_monthly_cap_usd == null ? {} : { AI_MONTHLY_CAP_USD = tostring(var.ai_monthly_cap_usd) },
  )

  api_environment = merge(local.shared_environment, {
    APP_ROLE                           = "api"
    DRAFT_QUEUE_URL                    = aws_sqs_queue.jobs.url
    GOOGLE_CLIENT_ID_SSM_PARAMETER     = var.google_client_id_parameter_name
    GOOGLE_CLIENT_SECRET_SSM_PARAMETER = var.google_client_secret_parameter_name
  })

  worker_environment = merge(local.shared_environment, {
    APP_ROLE                        = "worker"
    AWS_LWA_PASS_THROUGH_PATH       = "/events"
    ANTHROPIC_API_KEY_SSM_PARAMETER = var.anthropic_api_key_parameter_name
  })
}

# ---------------------------------------------------------------------------
# Queues
# ---------------------------------------------------------------------------

resource "aws_sqs_queue" "dlq" {
  name                      = "${var.name}-draft-jobs-dlq"
  message_retention_seconds = 14 * 24 * 60 * 60
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "jobs" {
  name                       = "${var.name}-draft-jobs"
  visibility_timeout_seconds = 6 * var.worker_timeout_s
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = 5
  })
}

resource "aws_sqs_queue_redrive_allow_policy" "dlq" {
  queue_url = aws_sqs_queue.dlq.id

  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.jobs.arn]
  })
}

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

resource "aws_iam_role" "api" {
  name = "${var.name}-api"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "api_vpc_access" {
  role       = aws_iam_role.api.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

# The parameters use the AWS-managed SSM key, whose key policy already lets SSM
# decrypt for callers in the account, so no KMS permission is needed.
resource "aws_iam_role_policy" "api" {
  name = "api"
  role = aws_iam_role.api.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "sqs:SendMessage"
        Resource = aws_sqs_queue.jobs.arn
      },
      {
        Effect = "Allow"
        Action = "ssm:GetParameter"
        Resource = [
          var.database_url_parameter_arn,
          var.google_client_id_parameter_arn,
          var.google_client_secret_parameter_arn,
        ]
      },
    ]
  })
}

resource "aws_iam_role" "worker" {
  name = "${var.name}-worker"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "worker_vpc_access" {
  role       = aws_iam_role.worker.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_iam_role_policy" "worker" {
  name = "worker"
  role = aws_iam_role.worker.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
        ]
        Resource = aws_sqs_queue.jobs.arn
      },
      {
        Effect = "Allow"
        Action = "ssm:GetParameter"
        Resource = [
          var.database_url_parameter_arn,
          var.anthropic_api_key_parameter_arn,
        ]
      },
    ]
  })
}

# ---------------------------------------------------------------------------
# Functions
# ---------------------------------------------------------------------------

resource "aws_lambda_function" "api" {
  function_name = "${var.name}-api"
  role          = aws_iam_role.api.arn
  package_type  = "Image"
  image_uri     = var.image_uri
  architectures = [var.architecture]
  timeout       = 29
  memory_size   = var.api_memory_mb

  vpc_config {
    subnet_ids                  = var.subnet_ids
    security_group_ids          = var.security_group_ids
    ipv6_allowed_for_dual_stack = true
  }

  logging_config {
    log_format = "JSON"
    log_group  = var.api_log_group_name
  }

  environment {
    variables = local.api_environment
  }

  depends_on = [aws_iam_role_policy_attachment.api_vpc_access]
}

resource "aws_lambda_function" "worker" {
  function_name = "${var.name}-worker"
  role          = aws_iam_role.worker.arn
  package_type  = "Image"
  image_uri     = var.image_uri
  architectures = [var.architecture]
  timeout       = var.worker_timeout_s
  memory_size   = var.worker_memory_mb

  vpc_config {
    subnet_ids                  = var.subnet_ids
    security_group_ids          = var.security_group_ids
    ipv6_allowed_for_dual_stack = true
  }

  logging_config {
    log_format = "JSON"
    log_group  = var.worker_log_group_name
  }

  environment {
    variables = local.worker_environment
  }

  depends_on = [aws_iam_role_policy_attachment.worker_vpc_access]
}

resource "aws_lambda_event_source_mapping" "worker" {
  event_source_arn = aws_sqs_queue.jobs.arn
  function_name    = aws_lambda_function.worker.arn
  batch_size       = 1

  # Lambda checks at create time that the role can read the queue.
  depends_on = [aws_iam_role_policy.worker]

  scaling_config {
    maximum_concurrency = var.worker_max_concurrency
  }
}

# ---------------------------------------------------------------------------
# HTTP API
# ---------------------------------------------------------------------------

resource "aws_apigatewayv2_api" "this" {
  name          = var.name
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "api" {
  api_id                 = aws_apigatewayv2_api.this.id
  integration_type       = "AWS_PROXY"
  integration_method     = "POST"
  integration_uri        = aws_lambda_function.api.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "default" {
  api_id    = aws_apigatewayv2_api.this.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.api.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.this.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_rate_limit  = var.api_throttle_rate
    throttling_burst_limit = var.api_throttle_burst
  }

  # Only request metadata is logged, never a body or a header.
  access_log_settings {
    destination_arn = var.api_access_log_group_arn
    format = jsonencode({
      requestId          = "$context.requestId"
      ip                 = "$context.identity.sourceIp"
      requestTime        = "$context.requestTime"
      httpMethod         = "$context.httpMethod"
      routeKey           = "$context.routeKey"
      status             = "$context.status"
      responseLength     = "$context.responseLength"
      integrationLatency = "$context.integrationLatency"
    })
  }
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowHttpApiInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.this.execution_arn}/*/*"
}
