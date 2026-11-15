terraform {
  required_version = ">= 1.11"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.71.0"
    }
    # The database module generates the master password with an ephemeral resource.
    random = {
      source  = "hashicorp/random"
      version = "3.9.1"
    }
  }
}
