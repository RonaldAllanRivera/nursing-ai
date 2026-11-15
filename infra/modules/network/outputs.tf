output "vpc_id" {
  description = "ID of the VPC."
  value       = aws_vpc.this.id
}

output "private_subnet_ids" {
  description = "IDs of the private subnets, in the order of the availability zones."
  value       = aws_subnet.private[*].id
}

output "app_security_group_id" {
  description = "ID of the security group for the Lambda functions."
  value       = aws_security_group.app.id
}

output "db_security_group_id" {
  description = "ID of the security group for the Aurora cluster."
  value       = aws_security_group.db.id
}

output "ipv6_cidr_block" {
  description = "IPv6 range that AWS assigned to the VPC."
  value       = aws_vpc.this.ipv6_cidr_block
}
