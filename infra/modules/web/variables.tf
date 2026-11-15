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

variable "price_class" {
  type        = string
  description = "CloudFront price class. PriceClass_200 includes the Philippines."
  default     = "PriceClass_200"
}
