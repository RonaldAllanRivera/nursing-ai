variable "name" {
  description = "Prefix for the names of the resources in this module, for example nursing-ai-demo."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,40}$", var.name))
    error_message = "name must be lowercase letters, digits and hyphens, at most 41 characters."
  }
}

variable "parameter_path" {
  description = "Path the secret parameters live under, for example /nursing-ai/demo. It starts with a slash and has no trailing slash."
  type        = string

  validation {
    condition     = can(regex("^/([A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*)$", var.parameter_path))
    error_message = "parameter_path must start with / and must not end with /."
  }
}

variable "alarm_email" {
  description = "Address that receives the alarm emails. The owner confirms the subscription from the first email."
  type        = string

  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+$", var.alarm_email))
    error_message = "alarm_email must be an email address containing @."
  }
}

variable "log_retention_days" {
  description = "How many days the log groups keep their logs. Must be a value CloudWatch Logs accepts."
  type        = number
  default     = 14

  validation {
    condition     = contains([1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288, 3653], var.log_retention_days)
    error_message = "log_retention_days must be one of the retention periods CloudWatch Logs allows."
  }
}

variable "api_function_name" {
  description = "Name of the API function. Its log group is created here, before the function, so the function can point at it."
  type        = string
}

variable "worker_function_name" {
  description = "Name of the worker function. Its log group is created here, before the function, so the function can point at it."
  type        = string
}

variable "http_api_id" {
  description = "ID of the HTTP API whose server errors the 5xx alarm watches."
  type        = string
}

variable "http_api_stage" {
  description = "Stage of the HTTP API that the 5xx alarm watches."
  type        = string
  default     = "$default"
}

variable "dlq_name" {
  description = "Name of the dead-letter queue the dead-jobs alarm watches."
  type        = string
}

variable "ai_spend_metric_namespace" {
  description = "CloudWatch namespace the application publishes its AI spend metric to."
  type        = string
  default     = "NursingAI"
}

variable "ai_spend_metric_name" {
  description = "Name of the AI spend metric, in US dollars, published without dimensions."
  type        = string
  default     = "AiSpendUsd"
}

variable "ai_daily_spend_alarm_usd" {
  description = "Daily AI spend, in US dollars, at or above which the AI spend alarm fires."
  type        = number
  default     = 1
}
