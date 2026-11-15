variable "name" {
  description = "Name of the image repository."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9]+([._/-][a-z0-9]+)*$", var.name))
    error_message = "name must be a valid ECR repository name: lowercase letters, digits and . _ / - separators."
  }
}
