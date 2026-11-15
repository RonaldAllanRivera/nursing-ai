mock_provider "aws" {
  mock_resource "aws_rds_cluster" {
    defaults = {
      endpoint = "nursing-ai-test.cluster-abc.ap-southeast-2.rds.amazonaws.com"
    }
  }
}

variables {
  name                        = "nursing-ai-test"
  subnet_ids                  = ["subnet-aaa", "subnet-bbb"]
  security_group_ids          = ["sg-111"]
  database_url_parameter_name = "/nursing-ai/test/database-url"
}

run "min_capacity_is_zero" {
  command = plan
  assert {
    condition     = aws_rds_cluster.this.serverlessv2_scaling_configuration[0].min_capacity == 0
    error_message = "the cluster must be able to scale to zero"
  }
  assert {
    condition     = aws_rds_cluster.this.serverlessv2_scaling_configuration[0].max_capacity == 1
    error_message = "the cluster must stop at 1 ACU"
  }
  assert {
    condition     = aws_rds_cluster.this.deletion_protection == true
    error_message = "deletion protection must be on"
  }
  assert {
    condition     = aws_rds_cluster.this.skip_final_snapshot == false
    error_message = "a final snapshot must be taken"
  }
  assert {
    condition     = aws_rds_cluster.this.final_snapshot_identifier == "nursing-ai-test-final"
    error_message = "the final snapshot must be named after the module's name"
  }
  assert {
    condition     = aws_rds_cluster_instance.writer.instance_class == "db.serverless"
    error_message = "the writer must be serverless"
  }
  assert {
    condition     = aws_rds_cluster.this.auto_minor_version_upgrade == false && aws_rds_cluster_instance.writer.auto_minor_version_upgrade == false
    error_message = "minor version upgrades must be off on the cluster and the writer"
  }
}

run "pauses_after_300_seconds" {
  command = plan
  assert {
    condition     = aws_rds_cluster.this.serverlessv2_scaling_configuration[0].seconds_until_auto_pause == 300
    error_message = "the cluster must pause after 5 idle minutes"
  }
}

run "storage_encrypted" {
  command = plan
  assert {
    condition     = aws_rds_cluster.this.storage_encrypted == true
    error_message = "storage must be encrypted"
  }
}

run "backups_kept_seven_days" {
  command = plan
  assert {
    condition     = aws_rds_cluster.this.backup_retention_period == 7
    error_message = "backups must be kept for 7 days"
  }
}

run "not_publicly_accessible" {
  command = plan
  assert {
    condition     = aws_rds_cluster_instance.writer.publicly_accessible == false
    error_message = "the instance must not be public"
  }
  assert {
    condition     = aws_db_subnet_group.this.name == "nursing-ai-test"
    error_message = "the subnet group must be named after the module's name"
  }
  assert {
    condition     = aws_rds_cluster.this.db_subnet_group_name == "nursing-ai-test"
    error_message = "the cluster must use the module's subnet group"
  }
  assert {
    condition     = toset(aws_db_subnet_group.this.subnet_ids) == toset(["subnet-aaa", "subnet-bbb"])
    error_message = "the subnet group must use the given subnets"
  }
  assert {
    condition     = toset(aws_rds_cluster.this.vpc_security_group_ids) == toset(["sg-111"])
    error_message = "the cluster must use the given security groups"
  }
}

run "password_never_in_state" {
  command = plan
  assert {
    condition     = aws_rds_cluster.this.master_password == null
    error_message = "the plain master_password must not be used"
  }
  assert {
    condition     = aws_rds_cluster.this.master_password_wo_version == 1
    error_message = "the write-only password must carry its version"
  }
  assert {
    condition     = aws_ssm_parameter.database_url.type == "SecureString"
    error_message = "the database URL must be a SecureString"
  }
  assert {
    condition     = aws_ssm_parameter.database_url.value_wo_version == 1
    error_message = "the URL must be written with the write-only argument"
  }
}

run "engine_version_must_match_local_pgvector" {
  command = plan
  variables {
    engine_version = "17.9"
  }
  expect_failures = [var.engine_version]
}

run "engine_version_17_10_is_accepted" {
  command = plan
  variables {
    engine_version = "17.10"
  }
  assert {
    condition     = aws_rds_cluster.this.engine_version == "17.10"
    error_message = "17.10 must be accepted"
  }
}

run "duplicate_subnets_are_refused" {
  command = plan
  variables {
    subnet_ids = ["subnet-aaa", "subnet-aaa"]
  }
  expect_failures = [var.subnet_ids]
}

run "no_security_group_is_refused" {
  command = plan
  variables {
    security_group_ids = []
  }
  expect_failures = [var.security_group_ids]
}
