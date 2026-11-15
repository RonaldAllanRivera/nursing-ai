variable "name" {
  description = "Name prefix for every resource in this module, for example nursing-ai-demo."
  type        = string
}

variable "cidr_block" {
  description = "IPv4 range of the VPC. Each subnet takes 8 more prefix bits: a /24 from the default /16."
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "Availability zones for the private subnets, one subnet each. At least two different ones, because an Aurora subnet group needs two."
  type        = list(string)
  default     = ["ap-southeast-2a", "ap-southeast-2b"]

  validation {
    condition     = length(var.availability_zones) >= 2 && length(distinct(var.availability_zones)) == length(var.availability_zones)
    error_message = "Use at least two different availability zones, each listed once: an Aurora subnet group needs two."
  }
}
