data "aws_caller_identity" "current" {}

# Denies every action. A deny beats every allow, so once this is attached the
# app's Lambda functions can no longer call AWS. To lift it, detach this policy
# from the two Lambda roles.
resource "aws_iam_policy" "deny_all" {
  name        = "${var.name}-brake-deny-all"
  description = "Denies every action. The budget brake attaches it to the app's Lambda roles when spend reaches the limit. Detach it from those roles to lift the brake."

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Deny"
      Action   = "*"
      Resource = "*"
    }]
  })
}

# The role AWS Budgets runs the action as. It can only attach or detach the
# deny-all policy, and only on the Lambda roles.
resource "aws_iam_role" "brake" {
  name = "${var.name}-brake"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "budgets.amazonaws.com" }
      Condition = {
        StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id }
      }
    }]
  })
}

resource "aws_iam_role_policy" "brake" {
  name = "attach-deny-all"
  role = aws_iam_role.brake.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["iam:AttachRolePolicy", "iam:DetachRolePolicy"]
      Resource = [for r in var.lambda_roles : r.arn]
      Condition = {
        ArnEquals = { "iam:PolicyARN" = aws_iam_policy.deny_all.arn }
      }
    }]
  })
}

resource "aws_budgets_budget_action" "brake" {
  budget_name        = var.budget_name
  action_type        = "APPLY_IAM_POLICY"
  approval_model     = "AUTOMATIC"
  notification_type  = "ACTUAL"
  execution_role_arn = aws_iam_role.brake.arn

  action_threshold {
    action_threshold_type  = "PERCENTAGE"
    action_threshold_value = var.threshold_percent
  }

  definition {
    iam_action_definition {
      policy_arn = aws_iam_policy.deny_all.arn
      roles      = [for r in var.lambda_roles : r.name]
    }
  }

  subscriber {
    address           = var.notify_email
    subscription_type = "EMAIL"
  }
}
