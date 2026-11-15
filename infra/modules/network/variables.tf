variable "name" {
  description = "Name prefix for every resource in this module, for example nursing-ai-demo."
  type        = string
}

variable "cidr_block" {
  description = "IPv4 range of the VPC. Each subnet takes a /24 from it."
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "Availability zones for the private subnets, one subnet each. At least two, because an Aurora subnet group needs two."
  type        = list(string)
  default     = ["ap-southeast-2a", "ap-southeast-2b"]

  validation {
    condition     = length(var.availability_zones) >= 2
    error_message = "Use at least two availability zones: an Aurora subnet group needs two."
  }
}
