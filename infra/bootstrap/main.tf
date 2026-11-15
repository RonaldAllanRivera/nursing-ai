data "aws_caller_identity" "current" {}

locals {
  github_host = "token.actions.githubusercontent.com"
}

# ---------------------------------------------------------------------------
# State bucket
# ---------------------------------------------------------------------------

resource "aws_s3_bucket" "state" {
  bucket = "${var.name}-tfstate-${data.aws_caller_identity.current.account_id}"

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id

  versioning_configuration {
    status = "Enabled"
  }
}

# Objects are encrypted with SSE-S3 (AES-256), which is free. A customer managed
# KMS key costs $1 a month, and in a one-account project access is already
# controlled by IAM and the bucket policy.
#trivy:ignore:AWS-0132
resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    bucket_key_enabled = true

    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket = aws_s3_bucket.state.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_policy" "state" {
  bucket = aws_s3_bucket.state.id

  # S3 can reject two settings of one bucket written at the same time
  # (OperationAborted), so the policy waits for the public access block.
  depends_on = [aws_s3_bucket_public_access_block.state]

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.state.arn,
          "${aws_s3_bucket.state.arn}/*",
        ]
        Condition = {
          Bool = { "aws:SecureTransport" = "false" }
        }
      }
    ]
  })
}

resource "aws_s3_bucket_lifecycle_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  # Versioning must be on before noncurrent versions can expire.
  depends_on = [aws_s3_bucket_versioning.state]

  rule {
    id     = "expire-old-state-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 90
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# ---------------------------------------------------------------------------
# GitHub OIDC (off until the account can create OIDC providers)
# ---------------------------------------------------------------------------

resource "aws_iam_openid_connect_provider" "github" {
  count = var.enable_github_oidc ? 1 : 0

  url            = "https://${local.github_host}"
  client_id_list = ["sts.amazonaws.com"]
}

# The trust policy, not the attached policy, is the gate for this role: only a
# workflow job that runs in the "production" environment can assume it, and
# that environment requires a reviewer's approval.
resource "aws_iam_role" "deploy" {
  count = var.enable_github_oidc ? 1 : 0

  name = "${var.name}-github-deploy"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Action    = "sts:AssumeRoleWithWebIdentity"
        Principal = { Federated = aws_iam_openid_connect_provider.github[0].arn }
        Condition = {
          StringEquals = {
            "${local.github_host}:aud" = "sts.amazonaws.com"
            "${local.github_host}:sub" = "repo:${var.github_repository}:environment:production"
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "deploy_admin" {
  count = var.enable_github_oidc ? 1 : 0

  role       = aws_iam_role.deploy[0].name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}

# Pull requests get this role. It can read the account's configuration and the
# Terraform state, but a deny policy below stops it decrypting SecureString
# parameters and reading objects, logs and queue messages, because a pull
# request's plan runs that pull request's own code. Pull-request plans therefore
# run as `terraform plan -refresh=false`: the AWS provider decrypts every SSM
# parameter it refreshes, so a refreshing plan would be refused. The workflow
# must use the `pull_request` trigger, never `pull_request_target`.
resource "aws_iam_role" "plan" {
  count = var.enable_github_oidc ? 1 : 0

  name = "${var.name}-github-plan"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Action    = "sts:AssumeRoleWithWebIdentity"
        Principal = { Federated = aws_iam_openid_connect_provider.github[0].arn }
        Condition = {
          StringEquals = {
            "${local.github_host}:aud" = "sts.amazonaws.com"
            "${local.github_host}:sub" = "repo:${var.github_repository}:pull_request"
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "plan_read_only" {
  count = var.enable_github_oidc ? 1 : 0

  role       = aws_iam_role.plan[0].name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

# A plan reads state and takes the state lock; the lock is a .tflock object
# next to the state file.
resource "aws_iam_role_policy" "plan_state_access" {
  count = var.enable_github_oidc ? 1 : 0

  name = "state-read-and-lock"
  role = aws_iam_role.plan[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadState"
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = "${aws_s3_bucket.state.arn}/*"
      },
      {
        Sid      = "TakeAndReleaseLock"
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:DeleteObject"]
        Resource = "${aws_s3_bucket.state.arn}/*.tflock"
      }
    ]
  })
}

resource "aws_iam_role_policy" "plan_deny_secrets_and_data" {
  count = var.enable_github_oidc ? 1 : 0

  name = "deny-secrets-and-app-data"
  role = aws_iam_role.plan[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "NoSecretDecryption"
        Effect   = "Deny"
        Action   = "kms:Decrypt"
        Resource = "*"
        Condition = {
          StringLike = { "kms:ViaService" = "ssm.*.amazonaws.com" }
        }
      },
      {
        Sid         = "NoObjectsOutsideState"
        Effect      = "Deny"
        Action      = ["s3:GetObject", "s3:GetObjectVersion"]
        NotResource = "${aws_s3_bucket.state.arn}/*"
      },
      {
        Sid      = "NoAppData"
        Effect   = "Deny"
        Resource = "*"
        Action = [
          "logs:GetLogEvents",
          "logs:FilterLogEvents",
          "logs:StartQuery",
          "logs:GetQueryResults",
          "logs:StartLiveTail",
          "logs:GetLogRecord",
          "logs:Unmask",
          "sqs:ReceiveMessage",
          "rds:DownloadDBLogFilePortion",
          "rds:DownloadCompleteDBLogFile",
          "secretsmanager:GetSecretValue",
        ]
      }
    ]
  })
}

# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------

# This budget was made by hand in the console. Importing it adopts it instead
# of making a second one.
import {
  to = aws_budgets_budget.monthly_guard
  id = "${data.aws_caller_identity.current.account_id}:monthly-guard"
}

resource "aws_budgets_budget" "monthly_guard" {
  name         = "monthly-guard"
  budget_type  = "COST"
  limit_amount = tostring(var.budget_limit_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_types {
    include_credit = false
    include_refund = false
  }

  dynamic "notification" {
    for_each = var.budget_alerts

    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value.threshold
      threshold_type             = notification.value.threshold_type
      notification_type          = notification.value.notification_type
      subscriber_email_addresses = [var.alert_email]
    }
  }
}

# ---------------------------------------------------------------------------
# Image registry (CI pushes the application image here before `live` applies)
# ---------------------------------------------------------------------------

module "registry" {
  source = "../modules/registry"

  name = var.name
}
