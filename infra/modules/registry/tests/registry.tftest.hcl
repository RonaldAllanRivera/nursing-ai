mock_provider "aws" {}

variables {
  name = "nursing-ai-test"
}

run "keeps_ten_images" {
  command = plan

  assert {
    condition     = length(jsondecode(aws_ecr_lifecycle_policy.app.policy).rules) == 1
    error_message = "the policy must have exactly one rule"
  }
  assert {
    condition     = jsondecode(aws_ecr_lifecycle_policy.app.policy).rules[0].selection.countType == "imageCountMoreThan"
    error_message = "the rule must count images"
  }
  assert {
    condition     = jsondecode(aws_ecr_lifecycle_policy.app.policy).rules[0].selection.countNumber == 10
    error_message = "the rule must keep the newest 10 images"
  }
  assert {
    condition     = jsondecode(aws_ecr_lifecycle_policy.app.policy).rules[0].selection.tagStatus == "any"
    error_message = "the rule must apply to every image"
  }
  assert {
    condition     = jsondecode(aws_ecr_lifecycle_policy.app.policy).rules[0].action.type == "expire"
    error_message = "the rule must expire old images"
  }
}

run "tags_immutable_and_scanned" {
  command = plan

  assert {
    condition     = aws_ecr_repository.app.name == "nursing-ai-test"
    error_message = "the repository is named from var.name"
  }
  assert {
    condition     = aws_ecr_repository.app.image_tag_mutability == "IMMUTABLE"
    error_message = "tags must be immutable"
  }
  assert {
    condition     = aws_ecr_repository.app.image_scanning_configuration[0].scan_on_push == true
    error_message = "images must be scanned on push"
  }
  assert {
    condition     = aws_ecr_repository.app.encryption_configuration[0].encryption_type == "AES256"
    error_message = "the repository must be encrypted with AES256"
  }
}
