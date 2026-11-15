output "repository_url" {
  description = "URL CI pushes the application image to."
  value       = aws_ecr_repository.app.repository_url
}

output "repository_arn" {
  description = "ARN of the image repository."
  value       = aws_ecr_repository.app.arn
}

output "repository_name" {
  description = "Name of the image repository."
  value       = aws_ecr_repository.app.name
}
