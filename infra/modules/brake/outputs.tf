output "deny_policy_arn" {
  description = "ARN of the deny-all policy the brake attaches. Detach it from the Lambda roles to lift the brake."
  value       = aws_iam_policy.deny_all.arn
  type        = string
}

output "brake_role_arn" {
  description = "ARN of the role AWS Budgets runs the brake as."
  value       = aws_iam_role.brake.arn
  type        = string
}

output "action_id" {
  description = "ID of the budget action."
  value       = aws_budgets_budget_action.brake.action_id
  type        = string
}

output "target_role_names" {
  description = "Names of the roles the budget action attaches the deny-all policy to."
  value       = aws_budgets_budget_action.brake.definition[0].iam_action_definition[0].roles
  type        = set(string)
}
