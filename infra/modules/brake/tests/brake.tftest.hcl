mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "123456789012"
    }
  }
}

# Give the two resources the tests compare distinct ARNs, so a policy pointing
# at the wrong one cannot pass by coincidence.
override_resource {
  target = aws_iam_policy.deny_all
  values = {
    arn = "arn:aws:iam::123456789012:policy/nursing-ai-test-brake-deny-all"
  }
}

override_resource {
  target = aws_iam_role.brake
  values = {
    id  = "nursing-ai-test-brake"
    arn = "arn:aws:iam::123456789012:role/nursing-ai-test-brake"
  }
}

variables {
  name         = "nursing-ai-test"
  notify_email = "owner@example.com"
  lambda_roles = [
    { name = "nursing-ai-test-api", arn = "arn:aws:iam::123456789012:role/nursing-ai-test-api" },
    { name = "nursing-ai-test-worker", arn = "arn:aws:iam::123456789012:role/nursing-ai-test-worker" },
  ]
}

run "brake_targets_lambda_roles" {
  command = apply

  assert {
    condition     = aws_budgets_budget_action.brake.budget_name == "monthly-guard"
    error_message = "The action must belong to the monthly-guard budget."
  }

  assert {
    condition     = length(aws_budgets_budget_action.brake.definition) == 1 && length(aws_budgets_budget_action.brake.definition[0].iam_action_definition) == 1
    error_message = "The action must have exactly one IAM action definition."
  }

  assert {
    condition     = aws_budgets_budget_action.brake.definition[0].iam_action_definition[0].roles == toset(["nursing-ai-test-api", "nursing-ai-test-worker"])
    error_message = "The action must target exactly the two Lambda roles, by name."
  }

  assert {
    condition     = aws_budgets_budget_action.brake.definition[0].iam_action_definition[0].policy_arn == aws_iam_policy.deny_all.arn
    error_message = "The action must attach the deny-all policy."
  }

  assert {
    condition     = aws_budgets_budget_action.brake.definition[0].iam_action_definition[0].policy_arn == "arn:aws:iam::123456789012:policy/nursing-ai-test-brake-deny-all"
    error_message = "The action's policy must be the deny-all policy's own ARN."
  }

  assert {
    condition     = aws_budgets_budget_action.brake.execution_role_arn == "arn:aws:iam::123456789012:role/nursing-ai-test-brake"
    error_message = "The action must run through the brake role."
  }

  assert {
    condition     = length(aws_budgets_budget_action.brake.subscriber) == 1 && one(aws_budgets_budget_action.brake.subscriber).address == "owner@example.com" && one(aws_budgets_budget_action.brake.subscriber).subscription_type == "EMAIL"
    error_message = "The action must email the owner, and only the owner."
  }

  assert {
    condition     = output.deny_policy_arn == aws_iam_policy.deny_all.arn && output.brake_role_arn == aws_iam_role.brake.arn
    error_message = "The outputs must expose the deny policy and the brake role."
  }
}

run "brake_fires_at_100_percent_actual_without_approval" {
  command = plan

  assert {
    condition     = aws_budgets_budget_action.brake.notification_type == "ACTUAL"
    error_message = "The brake must fire on actual spend, not a forecast."
  }

  assert {
    condition     = aws_budgets_budget_action.brake.action_threshold[0].action_threshold_type == "PERCENTAGE"
    error_message = "The threshold must be a percentage."
  }

  assert {
    condition     = aws_budgets_budget_action.brake.action_threshold[0].action_threshold_value == 100
    error_message = "The brake must fire at 100 percent."
  }

  assert {
    condition     = aws_budgets_budget_action.brake.approval_model == "AUTOMATIC"
    error_message = "The brake must not wait for approval."
  }

  assert {
    condition     = aws_budgets_budget_action.brake.action_type == "APPLY_IAM_POLICY"
    error_message = "The action must apply an IAM policy."
  }
}

run "threshold_can_be_changed" {
  command = plan

  variables {
    threshold_percent = 80
  }

  assert {
    condition     = aws_budgets_budget_action.brake.action_threshold[0].action_threshold_value == 80
    error_message = "threshold_percent must reach the action."
  }
}

run "deny_policy_denies_everything" {
  command = plan

  assert {
    condition     = aws_iam_policy.deny_all.name == "nursing-ai-test-brake-deny-all"
    error_message = "The deny policy name must come from var.name."
  }

  assert {
    condition     = length(jsondecode(aws_iam_policy.deny_all.policy).Statement) == 1
    error_message = "The deny policy must have exactly one statement."
  }

  assert {
    condition     = jsondecode(aws_iam_policy.deny_all.policy).Statement[0].Effect == "Deny"
    error_message = "The statement must be a Deny."
  }

  assert {
    condition     = jsondecode(aws_iam_policy.deny_all.policy).Statement[0].Action == "*"
    error_message = "The statement must deny every action."
  }

  assert {
    condition     = jsondecode(aws_iam_policy.deny_all.policy).Statement[0].Resource == "*"
    error_message = "The statement must deny on every resource."
  }

  assert {
    condition     = !contains(keys(jsondecode(aws_iam_policy.deny_all.policy).Statement[0]), "Condition")
    error_message = "The deny must have no condition that could let a call through."
  }

  assert {
    condition     = length(aws_iam_policy.deny_all.description) > 0 && strcontains(lower(aws_iam_policy.deny_all.description), "detach")
    error_message = "The description must say how to lift the deny."
  }
}

run "brake_role_can_only_attach_the_deny_policy" {
  command = apply

  assert {
    condition     = aws_iam_role.brake.name == "nursing-ai-test-brake"
    error_message = "The brake role name must come from var.name."
  }

  assert {
    condition     = length(jsondecode(aws_iam_role.brake.assume_role_policy).Statement) == 1
    error_message = "The trust policy must have exactly one statement."
  }

  assert {
    condition     = jsondecode(aws_iam_role.brake.assume_role_policy).Statement[0].Effect == "Allow" && jsondecode(aws_iam_role.brake.assume_role_policy).Statement[0].Action == "sts:AssumeRole"
    error_message = "The trust policy must allow sts:AssumeRole."
  }

  assert {
    condition     = jsondecode(aws_iam_role.brake.assume_role_policy).Statement[0].Principal == { Service = "budgets.amazonaws.com" }
    error_message = "Only the Budgets service may assume the brake role."
  }

  assert {
    condition     = jsondecode(aws_iam_role.brake.assume_role_policy).Statement[0].Condition == { StringEquals = { "aws:SourceAccount" = "123456789012" }, ArnLike = { "aws:SourceArn" = "arn:aws:budgets::123456789012:budget/*" } }
    error_message = "The trust must be limited to this account and its budgets with aws:SourceAccount and aws:SourceArn."
  }

  assert {
    condition     = aws_iam_role_policy.brake.role == "nursing-ai-test-brake"
    error_message = "The attach-and-detach policy must belong to the brake role."
  }

  assert {
    condition     = length(jsondecode(aws_iam_role_policy.brake.policy).Statement) == 1
    error_message = "The brake role's policy must have exactly one statement."
  }

  assert {
    condition     = jsondecode(aws_iam_role_policy.brake.policy).Statement[0].Effect == "Allow"
    error_message = "The brake role's statement must be an Allow."
  }

  assert {
    condition     = jsondecode(aws_iam_role_policy.brake.policy).Statement[0].Action == ["iam:AttachRolePolicy", "iam:DetachRolePolicy"]
    error_message = "The brake role may only attach and detach role policies."
  }

  assert {
    condition     = jsondecode(aws_iam_role_policy.brake.policy).Statement[0].Resource == ["arn:aws:iam::123456789012:role/nursing-ai-test-api", "arn:aws:iam::123456789012:role/nursing-ai-test-worker"]
    error_message = "The brake role may only act on exactly the two Lambda roles."
  }

  assert {
    condition     = jsondecode(aws_iam_role_policy.brake.policy).Statement[0].Condition == { ArnEquals = { "iam:PolicyARN" = "arn:aws:iam::123456789012:policy/nursing-ai-test-brake-deny-all" } }
    error_message = "The brake role may only attach the deny-all policy."
  }

  assert {
    condition     = jsondecode(aws_iam_role_policy.brake.policy).Statement[0].Condition.ArnEquals["iam:PolicyARN"] == aws_iam_policy.deny_all.arn
    error_message = "The policy condition must name the deny-all policy's ARN."
  }
}

run "rejects_no_lambda_roles" {
  command = plan

  variables {
    lambda_roles = []
  }

  expect_failures = [var.lambda_roles]
}

run "rejects_a_non_role_arn" {
  command = plan

  variables {
    lambda_roles = [{ name = "x", arn = "arn:aws:iam::123456789012:user/x" }]
  }

  expect_failures = [var.lambda_roles]
}

run "rejects_an_email_without_at_sign" {
  command = plan

  variables {
    notify_email = "nobody"
  }

  expect_failures = [var.notify_email]
}

run "rejects_a_zero_threshold" {
  command = plan

  variables {
    threshold_percent = 0
  }

  expect_failures = [var.threshold_percent]
}

run "budget_name_can_be_changed" {
  command = plan

  variables {
    budget_name = "other-budget"
  }

  assert {
    condition     = aws_budgets_budget_action.brake.budget_name == "other-budget"
    error_message = "budget_name must reach the action."
  }
}

run "rejects_a_role_whose_name_and_arn_disagree" {
  command = plan

  variables {
    lambda_roles = [{ name = "a", arn = "arn:aws:iam::123456789012:role/b" }]
  }

  expect_failures = [var.lambda_roles]
}

run "accepts_a_role_with_a_path" {
  command = plan

  variables {
    lambda_roles = [{ name = "a", arn = "arn:aws:iam::123456789012:role/app/a" }]
  }

  assert {
    condition     = one(aws_budgets_budget_action.brake.definition[0].iam_action_definition[0].roles) == "a"
    error_message = "A role ARN with a path must be accepted."
  }
}

run "rejects_an_arn_without_the_arn_aws_prefix" {
  command = plan

  variables {
    lambda_roles = [{ name = "x", arn = "iam:role/x" }]
  }

  expect_failures = [var.lambda_roles]
}

run "rejects_an_arn_without_role_segment" {
  command = plan

  variables {
    lambda_roles = [{ name = "x", arn = "arn:aws:iam::123456789012:user/x" }]
  }

  expect_failures = [var.lambda_roles]
}

run "rejects_an_invalid_name" {
  command = plan

  variables {
    name = "Bad_Name"
  }

  expect_failures = [var.name]
}

run "target_role_names_are_exposed" {
  command = plan

  assert {
    condition     = output.target_role_names == toset(["nursing-ai-test-api", "nursing-ai-test-worker"])
    error_message = "target_role_names must be the two role names the action targets."
  }
}

# Only the brake role's own policies are exclusive: anything added to it by
# hand is removed on the next apply. The Lambda roles are never made exclusive
# (an apply would detach the deny policy the budget action attached).
run "brake_role_policies_are_exclusive" {
  command = apply

  assert {
    condition     = aws_iam_role_policies_exclusive.brake.role_name == aws_iam_role.brake.name && aws_iam_role_policies_exclusive.brake.policy_names == toset([aws_iam_role_policy.brake.name])
    error_message = "The brake role may keep only its one inline policy; any other is removed."
  }

  assert {
    condition     = aws_iam_role_policy_attachments_exclusive.brake.role_name == aws_iam_role.brake.name && length(aws_iam_role_policy_attachments_exclusive.brake.policy_arns) == 0
    error_message = "The brake role may have no managed policy attached."
  }
}
