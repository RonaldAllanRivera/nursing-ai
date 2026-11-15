# The bucket name holds the account ID, so it is not written here. Pass it with
# -backend-config="bucket=<name>".
#
# This stack creates its own state bucket, so the first apply runs on local
# state through a git-ignored backend_override.tf (a file that swaps in the
# local backend). After that apply, delete backend_override.tf, then move the
# state into the new bucket with (with the override present this fails, because
# "bucket" is not expected for the local backend):
#   terraform init -migrate-state -backend-config="bucket=<the new bucket>"
terraform {
  backend "s3" {
    key          = "bootstrap/terraform.tfstate"
    region       = "ap-southeast-2"
    use_lockfile = true
    encrypt      = true
  }
}
