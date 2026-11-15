# The password exists only while Terraform runs. It is sent to write-only
# arguments, so it never reaches the state file or the plan.
ephemeral "random_password" "master" {
  length  = 40
  special = false # keeps the password safe to place inside a URL
}

resource "aws_db_subnet_group" "this" {
  name       = var.name
  subnet_ids = var.subnet_ids
}

# Storage is encrypted with the AWS-managed RDS key. A customer managed key
# would cost $1 a month and add nothing for a demo database.
#trivy:ignore:AWS-0079
resource "aws_rds_cluster" "this" {
  cluster_identifier = var.name
  engine             = "aurora-postgresql"
  engine_mode        = "provisioned"
  engine_version     = var.engine_version
  database_name      = var.database_name
  master_username    = var.master_username

  # Write-only: sent on create, and again only when password_version changes.
  master_password_wo         = ephemeral.random_password.master.result
  master_password_wo_version = var.password_version

  storage_encrypted       = true
  backup_retention_period = 7
  preferred_backup_window = "17:00-18:00" # UTC, which is 01:00 to 02:00 in Manila

  serverlessv2_scaling_configuration {
    min_capacity             = 0
    max_capacity             = 1
    seconds_until_auto_pause = 300
  }

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = var.security_group_ids

  deletion_protection       = true
  skip_final_snapshot       = false
  final_snapshot_identifier = "${var.name}-final"
  copy_tags_to_snapshot     = true
}

resource "aws_rds_cluster_instance" "writer" {
  identifier         = "${var.name}-writer"
  cluster_identifier = aws_rds_cluster.this.id
  instance_class     = "db.serverless"
  engine             = aws_rds_cluster.this.engine
  engine_version     = aws_rds_cluster.this.engine_version

  publicly_accessible = false

  # Keeps pgvector equal to the local image; upgrades are a reviewed version bump.
  auto_minor_version_upgrade = false
}

resource "aws_ssm_parameter" "database_url" {
  name        = var.database_url_parameter_name
  description = "Database URL of the ${var.name} Aurora cluster, read by the app at start."
  type        = "SecureString"

  # Write-only: rewritten together with the cluster password when password_version changes.
  value_wo         = "postgresql+asyncpg://${var.master_username}:${ephemeral.random_password.master.result}@${aws_rds_cluster.this.endpoint}:5432/${var.database_name}"
  value_wo_version = var.password_version
}
