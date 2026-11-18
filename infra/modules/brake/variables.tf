variable "name" {
  description = "Prefix for the names of the resources in this module, for example nursing-ai-demo."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,40}$", var.name))
    error_message = "name must be lowercase letters, digits and hyphens, at most 41 characters."
  }
}

variable "budget_name" {
  description = "Name of the existing monthly budget the brake is attached to. This module never creates a budget."
  type        = string
  default     = "monthly-guard"
}

variable "lambda_roles" {
  description = "The IAM roles of the app's Lambda functions: the brake attaches its deny-all policy to these and can touch nothing else."
  type = list(object({
    name = string
    arn  = string
  }))

  validation {
    condition     = length(var.lambda_roles) >= 1
    error_message = "lambda_roles needs at least one role."
  }

  validation {
    condition     = alltrue([for r in var.lambda_roles : startswith(r.arn, "arn:aws") && strcontains(r.arn, ":role/")])
    error_message = "Every lambda_roles arn must be an IAM role ARN (it starts with arn:aws and contains :role/)."
  }

  validation {
    condition     = alltrue([for r in var.lambda_roles : endswith(r.arn, ":role/${r.name}") || endswith(r.arn, "/${r.name}")])
    error_message = "Every lambda_roles name must be the role name at the end of its arn, so the brake role is allowed to touch the role the budget action names."
  }
}

variable "notify_email" {
  description = "Address that is emailed when the brake fires."
  type        = string
  sensitive   = true

  validation {
    condition     = strcontains(var.notify_email, "@")
    error_message = "notify_email must be an email address containing @."
  }
}

variable "threshold_percent" {
  description = "Percentage of the monthly budget, in actual spend, at which the brake fires."
  type        = number
  default     = 100

  validation {
    condition     = var.threshold_percent > 0
    error_message = "threshold_percent must be greater than 0."
  }
}
