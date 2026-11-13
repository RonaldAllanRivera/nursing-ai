output "state_bucket_name" {
  description = "Name of the S3 bucket that holds Terraform state."
  value       = aws_s3_bucket.state.bucket
}

output "deploy_role_arn" {
  description = "ARN of the role CI assumes to apply changes. Null while GitHub OIDC is off."
  value       = one(aws_iam_role.deploy[*].arn)
}

output "plan_role_arn" {
  description = "ARN of the read-only role CI assumes to plan pull requests. Null while GitHub OIDC is off."
  value       = one(aws_iam_role.plan[*].arn)
}

output "budget_name" {
  description = "Name of the monthly cost budget."
  value       = aws_budgets_budget.monthly_guard.name
}
