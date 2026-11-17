variable "name" {
  type        = string
  description = "Name prefix for the resources, for example nursing-ai-demo."
}

variable "api_origin_domain" {
  type        = string
  description = "Host name of the HTTP API, without https://. When set, /api/* is sent to it through this distribution, so the session cookie and the sign-in callback share one domain. Null leaves the route off."
  default     = null
  nullable    = true

  validation {
    condition     = var.api_origin_domain == null ? true : can(regex("^[^/:]+$", var.api_origin_domain))
    error_message = "api_origin_domain must be a bare host name: no https://, no port and no path."
  }
}

variable "custom_domain" {
  type        = string
  description = "Host name the distribution also answers to, for example sourceline.example.com. Null keeps only the cloudfront.net name. Needs certificate_arn."
  default     = null
  nullable    = true

  validation {
    condition     = var.custom_domain == null ? true : can(regex("^([a-z0-9]([a-z0-9-]*[a-z0-9])?\\.)+[a-z]([a-z0-9-]*[a-z0-9])?$", var.custom_domain))
    error_message = "custom_domain must be a lowercase host name with at least one dot: no scheme, no path and no trailing dot."
  }
}

variable "certificate_arn" {
  type        = string
  description = "ARN of the validated ACM certificate for custom_domain. CloudFront only reads certificates from us-east-1, so the caller makes it there. Set together with custom_domain, or both null."
  default     = null
  nullable    = true

  validation {
    condition     = (var.certificate_arn == null) == (var.custom_domain == null)
    error_message = "certificate_arn and custom_domain must be set together, or both left null."
  }

  validation {
    condition     = var.certificate_arn == null ? true : can(regex("^arn:aws:acm:us-east-1:[0-9]{12}:certificate/[0-9a-f-]+$", var.certificate_arn))
    error_message = "certificate_arn must be an ACM certificate ARN in us-east-1."
  }
}

variable "price_class" {
  type        = string
  description = "CloudFront price class. PriceClass_200 includes the Philippines."
  default     = "PriceClass_200"
}
