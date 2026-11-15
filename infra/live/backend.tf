# The state bucket's name holds the account ID, so it is not written here. Pass
# it with -backend-config="bucket=<name>" (and, on a PC, a matching profile).
terraform {
  backend "s3" {
    key          = "live/terraform.tfstate"
    region       = "ap-southeast-2"
    use_lockfile = true
    encrypt      = true
  }
}
