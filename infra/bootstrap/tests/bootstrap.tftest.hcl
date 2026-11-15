mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "123456789012"
    }
  }
}

# The budget is imported, and an import cannot run against a mock provider.
override_resource {
  target = aws_budgets_budget.monthly_guard
  values = {}
}

variables {
  alert_email = "alerts@example.com"
}

run "budget_excludes_credits" {
  command = plan

  assert {
    condition     = aws_budgets_budget.monthly_guard.cost_types[0].include_credit == false
    error_message = "credits must not count against the budget"
  }
  assert {
    condition     = aws_budgets_budget.monthly_guard.cost_types[0].include_refund == false
    error_message = "refunds must not count against the budget"
  }
  assert {
    condition     = aws_budgets_budget.monthly_guard.name == "monthly-guard"
    error_message = "the budget must be named monthly-guard"
  }
  assert {
    condition     = aws_budgets_budget.monthly_guard.limit_amount == "15"
    error_message = "the default limit must be 15"
  }
}

run "budget_alerts_match_the_credit_phase" {
  command = plan

  assert {
    condition     = length(aws_budgets_budget.monthly_guard.notification) == 4
    error_message = "expected four notifications"
  }
  assert {
    condition = toset([
      for n in aws_budgets_budget.monthly_guard.notification :
      "${n.threshold}|${n.threshold_type}|${n.notification_type}"
      ]) == toset([
      "5|ABSOLUTE_VALUE|ACTUAL",
      "10|ABSOLUTE_VALUE|ACTUAL",
      "100|PERCENTAGE|ACTUAL",
      "100|PERCENTAGE|FORECASTED",
    ])
    error_message = "alerts must be 5 and 10 dollars actual, 100 percent actual and 100 percent forecasted"
  }
  assert {
    condition = alltrue([
      for n in aws_budgets_budget.monthly_guard.notification :
      n.comparison_operator == "GREATER_THAN" && toset(n.subscriber_email_addresses) == toset(["alerts@example.com"])
    ])
    error_message = "every alert must fire when the amount is greater than the threshold and go to the alert email"
  }
}

run "state_bucket_configuration" {
  command = plan

  assert {
    condition     = one(aws_s3_bucket_server_side_encryption_configuration.state.rule).apply_server_side_encryption_by_default[0].sse_algorithm == "AES256" && one(aws_s3_bucket_server_side_encryption_configuration.state.rule).bucket_key_enabled == true
    error_message = "state bucket must use AES256 with a bucket key"
  }
  assert {
    condition     = one(aws_s3_bucket_ownership_controls.state.rule).object_ownership == "BucketOwnerEnforced"
    error_message = "state bucket ownership must be BucketOwnerEnforced"
  }
  assert {
    condition     = one(aws_s3_bucket_lifecycle_configuration.state.rule).noncurrent_version_expiration[0].noncurrent_days == 90
    error_message = "old state versions must expire after 90 days"
  }
  assert {
    condition     = one(aws_s3_bucket_lifecycle_configuration.state.rule).abort_incomplete_multipart_upload[0].days_after_initiation == 7
    error_message = "incomplete multipart uploads must be aborted after 7 days"
  }
}

run "state_bucket_versioned_private_and_tls_only" {
  # The policy embeds a computed ARN, so it is only known after apply (mocked).
  command = apply

  assert {
    condition     = aws_s3_bucket_versioning.state.versioning_configuration[0].status == "Enabled"
    error_message = "state bucket versioning must be Enabled"
  }
  assert {
    condition = alltrue([
      aws_s3_bucket_public_access_block.state.block_public_acls,
      aws_s3_bucket_public_access_block.state.block_public_policy,
      aws_s3_bucket_public_access_block.state.ignore_public_acls,
      aws_s3_bucket_public_access_block.state.restrict_public_buckets,
    ])
    error_message = "all four public access flags must be true"
  }
  assert {
    condition = anytrue([
      for s in jsondecode(aws_s3_bucket_policy.state.policy).Statement :
      s.Effect == "Deny" && s.Action == "s3:*" && s.Condition.Bool["aws:SecureTransport"] == "false" && contains(s.Resource, aws_s3_bucket.state.arn) && contains(s.Resource, "${aws_s3_bucket.state.arn}/*")
    ])
    error_message = "the bucket policy must deny requests that do not use TLS"
  }
  assert {
    condition     = aws_s3_bucket.state.bucket == "nursing-ai-tfstate-123456789012"
    error_message = "unexpected state bucket name"
  }
}

run "github_oidc_off_until_activation" {
  command = plan

  assert {
    condition     = length(aws_iam_openid_connect_provider.github) == 0
    error_message = "the OIDC provider must not exist by default"
  }
  assert {
    condition     = length(aws_iam_role.deploy) == 0 && length(aws_iam_role.plan) == 0
    error_message = "the CI roles must not exist by default"
  }
  assert {
    condition     = length(aws_iam_role_policy.plan_deny_secrets_and_data) == 0
    error_message = "the plan role's deny policy must not exist by default"
  }
  assert {
    condition     = output.deploy_role_arn == null && output.plan_role_arn == null
    error_message = "the role outputs must be null while OIDC is off"
  }
}

run "deploy_role_trusts_only_the_production_environment" {
  # The policy embeds a computed ARN, so it is only known after apply (mocked).
  command = apply

  variables {
    enable_github_oidc = true
    github_repository  = "example/nursing-ai"
  }

  assert {
    condition     = jsondecode(aws_iam_role.deploy[0].assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == "repo:example/nursing-ai:environment:production"
    error_message = "deploy role must trust only the production environment"
  }
  assert {
    condition     = jsondecode(aws_iam_role.deploy[0].assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:aud"] == "sts.amazonaws.com"
    error_message = "deploy role audience must be sts.amazonaws.com"
  }
  assert {
    condition     = length(jsondecode(aws_iam_role.deploy[0].assume_role_policy).Statement) == 1
    error_message = "deploy role must have exactly one trust statement"
  }
  assert {
    condition     = jsondecode(aws_iam_role.deploy[0].assume_role_policy).Statement[0].Principal.Federated == aws_iam_openid_connect_provider.github[0].arn
    error_message = "deploy role must trust the GitHub OIDC provider"
  }
}

run "plan_role_trusts_only_pull_requests" {
  # The policy embeds a computed ARN, so it is only known after apply (mocked).
  command = apply

  variables {
    enable_github_oidc = true
    github_repository  = "example/nursing-ai"
  }

  assert {
    condition     = jsondecode(aws_iam_role.plan[0].assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == "repo:example/nursing-ai:pull_request"
    error_message = "plan role must trust only pull requests"
  }
  assert {
    condition     = jsondecode(aws_iam_role.plan[0].assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:aud"] == "sts.amazonaws.com"
    error_message = "plan role audience must be sts.amazonaws.com"
  }
  assert {
    condition     = length(jsondecode(aws_iam_role.plan[0].assume_role_policy).Statement) == 1
    error_message = "plan role must have exactly one trust statement"
  }
  assert {
    condition     = jsondecode(aws_iam_role.plan[0].assume_role_policy).Statement[0].Principal.Federated == aws_iam_openid_connect_provider.github[0].arn
    error_message = "plan role must trust the GitHub OIDC provider"
  }
  assert {
    condition     = aws_iam_role_policy_attachment.plan_read_only[0].policy_arn == "arn:aws:iam::aws:policy/ReadOnlyAccess"
    error_message = "plan role must carry ReadOnlyAccess"
  }
  assert {
    condition = alltrue([
      for s in jsondecode(aws_iam_role_policy.plan_state_access[0].policy).Statement :
      s.Resource == "${aws_s3_bucket.state.arn}/*.tflock"
      if contains(flatten([s.Action]), "s3:PutObject") || contains(flatten([s.Action]), "s3:DeleteObject")
    ])
    error_message = "the plan role may write or delete only .tflock objects in the state bucket"
  }
}

run "plan_role_cannot_read_secrets_or_app_data" {
  # The policy embeds a computed ARN, so it is only known after apply (mocked).
  command = apply

  variables {
    enable_github_oidc = true
    github_repository  = "example/nursing-ai"
  }

  assert {
    condition = anytrue([
      for s in jsondecode(aws_iam_role_policy.plan_deny_secrets_and_data[0].policy).Statement :
      s.Effect == "Deny" && s.Action == "kms:Decrypt" && try(s.Condition.StringLike["kms:ViaService"], "") == "ssm.*.amazonaws.com"
    ])
    error_message = "the plan role must be denied kms:Decrypt through SSM"
  }
  assert {
    condition = anytrue([
      for s in jsondecode(aws_iam_role_policy.plan_deny_secrets_and_data[0].policy).Statement :
      s.Effect == "Deny" && try(s.NotResource, "") == "${aws_s3_bucket.state.arn}/*" && contains(flatten([s.Action]), "s3:GetObject")
    ])
    error_message = "the plan role must be denied reading S3 objects outside the state bucket"
  }
  assert {
    condition = anytrue([
      for s in jsondecode(aws_iam_role_policy.plan_deny_secrets_and_data[0].policy).Statement :
      s.Effect == "Deny" && contains(flatten([s.Action]), "logs:GetLogEvents") && contains(flatten([s.Action]), "sqs:ReceiveMessage") && contains(flatten([s.Action]), "secretsmanager:GetSecretValue")
    ])
    error_message = "the plan role must be denied reading logs, queue messages and secrets"
  }
}

run "oidc_needs_a_repository" {
  command = plan

  variables {
    enable_github_oidc = true
  }

  expect_failures = [var.github_repository]
}
