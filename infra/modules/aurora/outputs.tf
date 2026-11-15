output "cluster_arn" {
  description = "ARN of the Aurora cluster."
  value       = aws_rds_cluster.this.arn
}

output "cluster_identifier" {
  description = "Identifier of the Aurora cluster."
  value       = aws_rds_cluster.this.cluster_identifier
}

output "endpoint" {
  description = "Writer endpoint of the cluster."
  value       = aws_rds_cluster.this.endpoint
}

output "database_url_parameter_arn" {
  description = "ARN of the SSM parameter that holds the database URL, for an IAM policy that lets the app read it."
  value       = aws_ssm_parameter.database_url.arn
}

output "database_url_parameter_name" {
  description = "Name of the SSM parameter that holds the database URL, for the app to read at start."
  value       = aws_ssm_parameter.database_url.name
}
