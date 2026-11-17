locals {
  default_tags = {
    project     = "nursing-ai"
    environment = var.environment
    managed_by  = "terraform"
    stack       = "live"
  }
}

provider "aws" {
  region  = var.region
  profile = var.aws_profile

  default_tags {
    tags = local.default_tags
  }
}

# CloudFront only accepts certificates from us-east-1. The same profile and tags
# as the main provider; only the web module's certificate uses it.
provider "aws" {
  alias   = "us_east_1"
  region  = "us-east-1"
  profile = var.aws_profile

  default_tags {
    tags = local.default_tags
  }
}
