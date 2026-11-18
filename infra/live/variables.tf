variable "region" {
  description = "AWS region for everything this stack creates."
  type        = string
  default     = "ap-southeast-2"
}

variable "aws_profile" {
  description = "Named AWS CLI profile to sign in with. Null uses the default credential chain, which is how CI signs in (through OIDC). On a PC, use the nursing-ai profile."
  type        = string
  default     = null
  nullable    = true
}

variable "environment" {
  description = "Which environment this stack is: demo or prod. It names every resource and sets the app's APP_ENV. Use one environment per AWS account: prod gets its own account, its own bootstrap and its own state bucket, because the state key, the account-wide monthly-guard budget, the brake and the AI-spend metric are all per account."
  type        = string
  default     = "demo"

  validation {
    condition     = contains(["demo", "prod"], var.environment)
    error_message = "environment must be demo or prod."
  }
}

variable "image_uri" {
  description = "Full URI of the application container image, including its tag. CI passes the image it just pushed."
  type        = string

  validation {
    condition     = length(var.image_uri) > 0
    error_message = "image_uri must not be empty."
  }
}

variable "alert_email" {
  description = "Address that receives the alarm emails and the budget brake notice."
  type        = string
  sensitive   = true

  validation {
    condition     = strcontains(var.alert_email, "@")
    error_message = "alert_email must be an email address containing @."
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
  nullable    = true
}

variable "availability_zones" {
  description = "Availability zones for the private subnets. At least two different ones, because the database needs two."
  type        = list(string)
  default     = ["ap-southeast-2a", "ap-southeast-2b"]
}

variable "ai_daily_spend_alarm_usd" {
  description = "Daily AI spend, in US dollars, at or above which the AI spend alarm fires."
  type        = number
  default     = 1
}

variable "domain_name" {
  description = "Custom host name for the site, a subdomain of your own domain whose DNS stays elsewhere (for example sourceline.example.com). Set it with TF_VAR_domain_name so the name is never committed. Null keeps the cloudfront.net address. Setting it requests a certificate and fills the dns_records output; add those two records, then set domain_validated. The site-url parameter changes with domain_validated, and the functions read it at cold start, so the new address takes effect after the next deploy."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.domain_name == null ? true : can(regex("^([a-z0-9]([a-z0-9-]*[a-z0-9])?\\.)+[a-z]([a-z0-9-]*[a-z0-9])?$", var.domain_name))
    error_message = "domain_name must be a lowercase host name with at least one dot: no scheme, no path and no trailing dot."
  }
}

variable "domain_validated" {
  description = "Set to true (TF_VAR_domain_validated=true) in a second apply, after the two dns_records are in DNS. It makes the apply wait for the certificate, adds the CloudFront alias and certificate, and points site-url at the custom domain. Leave false before that, or the apply would wait for records that are not there."
  type        = bool
  default     = false

  validation {
    condition     = !var.domain_validated || var.domain_name != null
    error_message = "domain_validated needs a domain_name."
  }
}

variable "database_password_version" {
  description = "Version of the generated database password. Raise it by one to rotate the password, or after an apply that stopped between creating the cluster and writing the database URL parameter."
  type        = number
  default     = 1

  validation {
    condition     = var.database_password_version > 0
    error_message = "database_password_version must be 1 or more."
  }
}
