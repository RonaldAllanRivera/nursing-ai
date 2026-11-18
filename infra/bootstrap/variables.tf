variable "region" {
  description = "AWS region for everything this stack creates."
  type        = string
  default     = "ap-southeast-2"
}

variable "aws_profile" {
  description = "Named AWS CLI profile to sign in with. This stack only runs from the owner's PC. Null uses the default credential chain."
  type        = string
  default     = "nursing-ai"
  nullable    = true
}

variable "name" {
  description = "Prefix for the names of the resources in this stack."
  type        = string
  default     = "nursing-ai"
}

variable "alert_email" {
  description = "Email address that receives the budget alerts."
  type        = string
  sensitive   = true

  validation {
    condition     = can(regex("@", var.alert_email))
    error_message = "alert_email must contain an @."
  }
}

variable "budget_limit_usd" {
  description = "Monthly cost limit in US dollars."
  type        = number
  default     = 15
}

variable "budget_alerts" {
  description = "Budget alerts. threshold is a dollar amount for ABSOLUTE_VALUE or a percent of the limit for PERCENTAGE."
  type = list(object({
    threshold         = number
    threshold_type    = string
    notification_type = string
  }))
  default = [
    { threshold = 5, threshold_type = "ABSOLUTE_VALUE", notification_type = "ACTUAL" },
    { threshold = 10, threshold_type = "ABSOLUTE_VALUE", notification_type = "ACTUAL" },
    { threshold = 100, threshold_type = "PERCENTAGE", notification_type = "ACTUAL" },
    { threshold = 100, threshold_type = "PERCENTAGE", notification_type = "FORECASTED" },
  ]

  validation {
    condition     = alltrue([for a in var.budget_alerts : contains(["ABSOLUTE_VALUE", "PERCENTAGE"], a.threshold_type)])
    error_message = "threshold_type must be ABSOLUTE_VALUE or PERCENTAGE."
  }

  validation {
    condition     = alltrue([for a in var.budget_alerts : contains(["ACTUAL", "FORECASTED"], a.notification_type)])
    error_message = "notification_type must be ACTUAL or FORECASTED."
  }
}

variable "enable_github_oidc" {
  description = "Create the GitHub OIDC provider and the two CI roles. Leave false until the account can create OIDC providers."
  type        = bool
  default     = false
}

variable "github_repository" {
  description = "GitHub repository in owner/repo form that the CI roles trust. Required when enable_github_oidc is true."
  type        = string
  default     = null

  validation {
    condition     = var.github_repository == null || can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must look like owner/repo."
  }

  validation {
    condition     = !var.enable_github_oidc || var.github_repository != null
    error_message = "github_repository is required when enable_github_oidc is true."
  }
}
