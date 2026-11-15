variable "name" {
  description = "Prefix for the names of the resources in this module, for example nursing-ai-demo."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,40}$", var.name))
    error_message = "name must be lowercase letters, digits and hyphens, at most 41 characters."
  }
}

variable "image_uri" {
  description = "Full URI of the application container image, including its tag, that both functions run."
  type        = string

  validation {
    condition     = length(var.image_uri) > 0
    error_message = "image_uri must not be empty."
  }
}

variable "subnet_ids" {
  description = "Private dual-stack subnets the functions attach to."
  type        = list(string)

  validation {
    condition     = length(var.subnet_ids) >= 1
    error_message = "Give at least one subnet."
  }
}

variable "security_group_ids" {
  description = "Security groups for the functions' network interfaces."
  type        = list(string)

  validation {
    condition     = length(var.security_group_ids) >= 1
    error_message = "Give at least one security group."
  }
}

variable "app_env" {
  description = "Value of the APP_ENV setting."
  type        = string
  default     = "demo"

  validation {
    condition     = contains(["demo", "prod"], var.app_env)
    error_message = "app_env must be demo or prod."
  }
}

variable "ai_mode" {
  description = "How the app produces AI output: mock, replay or live."
  type        = string
  default     = "mock"

  validation {
    condition     = contains(["mock", "replay", "live"], var.ai_mode)
    error_message = "ai_mode must be mock, replay or live."
  }
}

variable "ai_monthly_cap_usd" {
  description = "Monthly AI spending cap in US dollars. Null leaves the setting out so the app's own default applies."
  type        = number
  default     = null

  validation {
    condition     = var.ai_monthly_cap_usd == null || var.ai_monthly_cap_usd >= 0
    error_message = "ai_monthly_cap_usd must be zero or more."
  }
}

variable "database_url_parameter_arn" {
  description = "ARN of the SecureString that holds the database URL."
  type        = string
}

variable "database_url_parameter_name" {
  description = "Name of the SecureString that holds the database URL. The app reads it at cold start."
  type        = string
}

variable "anthropic_api_key_parameter_arn" {
  description = "ARN of the SecureString that holds the Anthropic API key. Only the worker may read it."
  type        = string
}

variable "anthropic_api_key_parameter_name" {
  description = "Name of the SecureString that holds the Anthropic API key."
  type        = string
}

variable "google_client_id_parameter_arn" {
  description = "ARN of the SecureString that holds the Google sign-in client ID. Only the API may read it."
  type        = string
}

variable "google_client_id_parameter_name" {
  description = "Name of the SecureString that holds the Google sign-in client ID."
  type        = string
}

variable "google_client_secret_parameter_arn" {
  description = "ARN of the SecureString that holds the Google sign-in client secret. Only the API may read it."
  type        = string
}

variable "google_client_secret_parameter_name" {
  description = "Name of the SecureString that holds the Google sign-in client secret."
  type        = string
}

variable "api_log_group_name" {
  description = "Name of the log group the API function writes to."
  type        = string
}

variable "worker_log_group_name" {
  description = "Name of the log group the worker function writes to."
  type        = string
}

variable "api_access_log_group_arn" {
  description = "ARN of the log group that receives the HTTP API's access log."
  type        = string
}

variable "api_memory_mb" {
  description = "Memory for the API function, in MB."
  type        = number
  default     = 1024

  validation {
    condition     = var.api_memory_mb >= 128 && var.api_memory_mb <= 10240
    error_message = "api_memory_mb must be between 128 and 10240."
  }
}

variable "worker_memory_mb" {
  description = "Memory for the worker function, in MB."
  type        = number
  default     = 1024

  validation {
    condition     = var.worker_memory_mb >= 128 && var.worker_memory_mb <= 10240
    error_message = "worker_memory_mb must be between 128 and 10240."
  }
}

variable "worker_timeout_s" {
  description = "Timeout for the worker function, in seconds. The queue's visibility timeout is six times this."
  type        = number
  default     = 120

  validation {
    condition     = var.worker_timeout_s >= 1 && var.worker_timeout_s <= 900
    error_message = "worker_timeout_s must be between 1 and 900."
  }
}

variable "worker_max_concurrency" {
  description = "Most worker invocations that may run at once. SQS requires at least 2."
  type        = number
  default     = 2

  validation {
    condition     = var.worker_max_concurrency >= 2 && var.worker_max_concurrency <= 10
    error_message = "worker_max_concurrency must be between 2 and 10."
  }
}

variable "api_throttle_rate" {
  description = "Steady requests per second the HTTP API accepts."
  type        = number
  default     = 10

  validation {
    condition     = var.api_throttle_rate >= 1
    error_message = "api_throttle_rate must be at least 1."
  }
}

variable "api_throttle_burst" {
  description = "Burst of requests the HTTP API accepts above the steady rate."
  type        = number
  default     = 20

  validation {
    condition     = var.api_throttle_burst >= 1
    error_message = "api_throttle_burst must be at least 1."
  }
}

variable "architecture" {
  description = "CPU architecture of the container image: x86_64 or arm64."
  type        = string
  default     = "x86_64"

  validation {
    condition     = contains(["x86_64", "arm64"], var.architecture)
    error_message = "architecture must be x86_64 or arm64."
  }
}
