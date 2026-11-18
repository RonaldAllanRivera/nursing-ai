variable "name" {
  description = "Prefix for the names of the resources in this module, for example nursing-ai-demo."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,40}$", var.name))
    error_message = "name must be lowercase letters, digits and hyphens, at most 41 characters."
  }
}

variable "image_uri" {
  description = "Full URI of the application container image, including its tag, that all three functions run."
  type        = string
  sensitive   = true

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

  validation {
    condition     = can(regex("^arn:aws[a-z-]*:ssm:", var.database_url_parameter_arn))
    error_message = "database_url_parameter_arn must be an SSM parameter ARN (arn:aws:ssm:...)."
  }

  validation {
    condition     = endswith(var.database_url_parameter_arn, ":parameter${var.database_url_parameter_name}")
    error_message = "database_url_parameter_arn must be the ARN of the parameter named database_url_parameter_name."
  }
}

variable "database_url_parameter_name" {
  description = "Name of the SecureString that holds the database URL. The app reads it at cold start."
  type        = string

  validation {
    condition     = startswith(var.database_url_parameter_name, "/")
    error_message = "database_url_parameter_name must be a parameter name that starts with /."
  }
}

variable "anthropic_api_key_parameter_arn" {
  description = "ARN of the SecureString that holds the Anthropic API key. Only the worker may read it."
  type        = string

  validation {
    condition     = can(regex("^arn:aws[a-z-]*:ssm:", var.anthropic_api_key_parameter_arn))
    error_message = "anthropic_api_key_parameter_arn must be an SSM parameter ARN (arn:aws:ssm:...)."
  }

  validation {
    condition     = endswith(var.anthropic_api_key_parameter_arn, ":parameter${var.anthropic_api_key_parameter_name}")
    error_message = "anthropic_api_key_parameter_arn must be the ARN of the parameter named anthropic_api_key_parameter_name."
  }
}

variable "anthropic_api_key_parameter_name" {
  description = "Name of the SecureString that holds the Anthropic API key."
  type        = string

  validation {
    condition     = startswith(var.anthropic_api_key_parameter_name, "/")
    error_message = "anthropic_api_key_parameter_name must be a parameter name that starts with /."
  }
}

variable "google_client_id_parameter_arn" {
  description = "ARN of the SecureString that holds the Google sign-in client ID. Only the API may read it."
  type        = string

  validation {
    condition     = can(regex("^arn:aws[a-z-]*:ssm:", var.google_client_id_parameter_arn))
    error_message = "google_client_id_parameter_arn must be an SSM parameter ARN (arn:aws:ssm:...)."
  }

  validation {
    condition     = endswith(var.google_client_id_parameter_arn, ":parameter${var.google_client_id_parameter_name}")
    error_message = "google_client_id_parameter_arn must be the ARN of the parameter named google_client_id_parameter_name."
  }
}

variable "google_client_id_parameter_name" {
  description = "Name of the SecureString that holds the Google sign-in client ID."
  type        = string

  validation {
    condition     = startswith(var.google_client_id_parameter_name, "/")
    error_message = "google_client_id_parameter_name must be a parameter name that starts with /."
  }
}

variable "google_client_secret_parameter_arn" {
  description = "ARN of the SecureString that holds the Google sign-in client secret. Only the API may read it."
  type        = string

  validation {
    condition     = can(regex("^arn:aws[a-z-]*:ssm:", var.google_client_secret_parameter_arn))
    error_message = "google_client_secret_parameter_arn must be an SSM parameter ARN (arn:aws:ssm:...)."
  }

  validation {
    condition     = endswith(var.google_client_secret_parameter_arn, ":parameter${var.google_client_secret_parameter_name}")
    error_message = "google_client_secret_parameter_arn must be the ARN of the parameter named google_client_secret_parameter_name."
  }
}

variable "google_client_secret_parameter_name" {
  description = "Name of the SecureString that holds the Google sign-in client secret."
  type        = string

  validation {
    condition     = startswith(var.google_client_secret_parameter_name, "/")
    error_message = "google_client_secret_parameter_name must be a parameter name that starts with /."
  }
}

variable "site_url_parameter_arn" {
  description = "ARN of the parameter that holds the site address (an origin such as https://d111111abcdef8.cloudfront.net). Every function may read it."
  type        = string

  validation {
    condition     = can(regex("^arn:aws[a-z-]*:ssm:", var.site_url_parameter_arn))
    error_message = "site_url_parameter_arn must be an SSM parameter ARN (arn:aws:ssm:...)."
  }

  validation {
    condition     = endswith(var.site_url_parameter_arn, ":parameter${var.site_url_parameter_name}")
    error_message = "site_url_parameter_arn must be the ARN of the parameter named site_url_parameter_name."
  }
}

variable "site_url_parameter_name" {
  description = "Name of the parameter that holds the site address (an origin such as https://d111111abcdef8.cloudfront.net)."
  type        = string

  validation {
    condition     = startswith(var.site_url_parameter_name, "/")
    error_message = "site_url_parameter_name must be a parameter name that starts with /."
  }
}

variable "bootstrap_admin_email_parameter_arn" {
  description = "ARN of the parameter that holds the bootstrap admin email. Only the API may read it."
  type        = string

  validation {
    condition     = can(regex("^arn:aws[a-z-]*:ssm:", var.bootstrap_admin_email_parameter_arn))
    error_message = "bootstrap_admin_email_parameter_arn must be an SSM parameter ARN (arn:aws:ssm:...)."
  }

  validation {
    condition     = endswith(var.bootstrap_admin_email_parameter_arn, ":parameter${var.bootstrap_admin_email_parameter_name}")
    error_message = "bootstrap_admin_email_parameter_arn must be the ARN of the parameter named bootstrap_admin_email_parameter_name."
  }
}

variable "bootstrap_admin_email_parameter_name" {
  description = "Name of the parameter that holds the bootstrap admin email."
  type        = string

  validation {
    condition     = startswith(var.bootstrap_admin_email_parameter_name, "/")
    error_message = "bootstrap_admin_email_parameter_name must be a parameter name that starts with /."
  }
}

variable "api_log_group_name" {
  description = "Name of the log group the API function writes to."
  type        = string
}

variable "worker_log_group_name" {
  description = "Name of the log group the worker function writes to."
  type        = string
}

variable "ops_log_group_name" {
  description = "Name of the log group the ops function writes to."
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

variable "ops_memory_mb" {
  description = "Memory for the ops function, in MB. It runs migrations, the demo seed and the smoke check."
  type        = number
  default     = 1024

  validation {
    condition     = var.ops_memory_mb >= 128 && var.ops_memory_mb <= 10240
    error_message = "ops_memory_mb must be between 128 and 10240."
  }
}

variable "ops_timeout_s" {
  description = "Timeout for the ops function, in seconds. A migration may wait for a paused database to wake."
  type        = number
  default     = 300

  validation {
    condition     = var.ops_timeout_s >= 1 && var.ops_timeout_s <= 900
    error_message = "ops_timeout_s must be between 1 and 900."
  }
}

variable "idle_lock_minutes" {
  description = "Minutes of inactivity after which the API asks for the PIN again (the IDLE_LOCK_MINUTES setting)."
  type        = number
  default     = 5

  validation {
    condition     = var.idle_lock_minutes >= 1
    error_message = "idle_lock_minutes must be at least 1."
  }
}

variable "ai_daily_drafts_per_user" {
  description = "Most drafts one invited user may start in a day (the AI_DAILY_DRAFTS_PER_USER setting)."
  type        = number
  default     = 20

  validation {
    condition     = var.ai_daily_drafts_per_user >= 1
    error_message = "ai_daily_drafts_per_user must be at least 1."
  }
}
