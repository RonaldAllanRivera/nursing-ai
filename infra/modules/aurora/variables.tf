variable "name" {
  description = "Name prefix for every resource in this module, for example nursing-ai-demo."
  type        = string
}

variable "subnet_ids" {
  description = "Private subnets for the database, in at least two availability zones (an Aurora subnet group needs two)."
  type        = list(string)

  validation {
    condition     = length(distinct(var.subnet_ids)) >= 2
    error_message = "Give at least two different subnets: an Aurora subnet group needs two availability zones."
  }
}

variable "security_group_ids" {
  description = "Security groups attached to the database cluster. At least one: an empty list would fall back to the VPC's default group."
  type        = list(string)

  validation {
    condition     = length(var.security_group_ids) >= 1
    error_message = "Give at least one security group: an empty list would fall back to the VPC's default group."
  }
}

variable "engine_version" {
  description = "Aurora PostgreSQL version. Only the Aurora 17 versions that ship pgvector 0.8.2 (the version of the local development image) are allowed; moving to another version is a reviewed change that also moves the local image."
  type        = string
  default     = "17.11"

  validation {
    condition     = contains(["17.10", "17.11"], var.engine_version)
    error_message = "engine_version must be 17.10 or 17.11: the Aurora 17 versions with pgvector 0.8.2, the version of the local image."
  }
}

variable "database_name" {
  description = "Name of the database created in the cluster."
  type        = string
  default     = "nursing"
}

variable "master_username" {
  description = "Name of the cluster's master user."
  type        = string
  default     = "nursing_admin"
}

variable "password_version" {
  description = "Version of the generated master password. Raise it by one to rotate the password: the cluster and the stored database URL are then both rewritten with the same new value. Also raise it if an apply stops after the cluster is created but before the parameter is written, or if the parameter is ever recreated: each run generates a new password, so the stored URL would otherwise carry one the cluster never got, and nothing fails until the app cannot log in."
  type        = number
  default     = 1
}

variable "database_url_parameter_name" {
  description = "Name of the SSM parameter the database URL is written to, for example /nursing-ai/demo/database-url."
  type        = string
}
