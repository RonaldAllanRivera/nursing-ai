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
      s.Effect == "Deny" && s.Condition.Bool["aws:SecureTransport"] == "false"
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
}

run "oidc_needs_a_repository" {
  command = plan

  variables {
    enable_github_oidc = true
  }

  expect_failures = [var.github_repository]
}
