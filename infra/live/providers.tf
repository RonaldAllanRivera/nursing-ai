provider "aws" {
  region  = var.region
  profile = var.aws_profile

  default_tags {
    tags = {
      project     = "nursing-ai"
      environment = var.environment
      managed_by  = "terraform"
      stack       = "live"
    }
  }
}
