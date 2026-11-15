locals {
  name           = "nursing-ai-${var.environment}"
  parameter_path = "/nursing-ai/${var.environment}"

  # Compute names its functions "<name>-api" and "<name>-worker". Ops makes the
  # log groups before the functions exist, so it needs the same names. A test
  # checks that the two agree.
  api_function_name    = "${local.name}-api"
  worker_function_name = "${local.name}-worker"
}

module "network" {
  source = "../modules/network"

  name               = local.name
  availability_zones = var.availability_zones
}

module "aurora" {
  source = "../modules/aurora"

  name                        = local.name
  subnet_ids                  = module.network.private_subnet_ids
  security_group_ids          = [module.network.db_security_group_id]
  password_version            = var.database_password_version
  database_url_parameter_name = "${local.parameter_path}/database-url"
}

# Ops reads compute's API ID and queue name for its alarms, and compute reads
# ops's log groups and parameters. Terraform orders the resources, not the
# modules, so the log groups still exist before the functions.
module "ops" {
  source = "../modules/ops"

  name                     = local.name
  parameter_path           = local.parameter_path
  alarm_email              = var.alert_email
  api_function_name        = local.api_function_name
  worker_function_name     = local.worker_function_name
  http_api_id              = module.compute.http_api_id
  dlq_name                 = module.compute.dlq_name
  ai_daily_spend_alarm_usd = var.ai_daily_spend_alarm_usd
}

module "compute" {
  source = "../modules/compute"

  name               = local.name
  image_uri          = var.image_uri
  subnet_ids         = module.network.private_subnet_ids
  security_group_ids = [module.network.app_security_group_id]

  app_env            = var.environment
  ai_mode            = var.ai_mode
  ai_monthly_cap_usd = var.ai_monthly_cap_usd

  database_url_parameter_arn          = module.aurora.database_url_parameter_arn
  database_url_parameter_name         = module.aurora.database_url_parameter_name
  anthropic_api_key_parameter_arn     = module.ops.parameter_arns["anthropic-api-key"]
  anthropic_api_key_parameter_name    = module.ops.parameter_names["anthropic-api-key"]
  google_client_id_parameter_arn      = module.ops.parameter_arns["google-client-id"]
  google_client_id_parameter_name     = module.ops.parameter_names["google-client-id"]
  google_client_secret_parameter_arn  = module.ops.parameter_arns["google-client-secret"]
  google_client_secret_parameter_name = module.ops.parameter_names["google-client-secret"]

  api_log_group_name       = module.ops.api_log_group_name
  worker_log_group_name    = module.ops.worker_log_group_name
  api_access_log_group_arn = module.ops.api_access_log_group_arn
}

module "web" {
  source = "../modules/web"

  name = local.name
  # Compute's endpoint starts with https://; the web module wants the bare host.
  api_origin_domain = trimprefix(module.compute.api_endpoint, "https://")
}

module "brake" {
  source = "../modules/brake"

  name = local.name
  lambda_roles = [
    { name = module.compute.api_role_name, arn = module.compute.api_role_arn },
    { name = module.compute.worker_role_name, arn = module.compute.worker_role_arn },
  ]
  notify_email = var.alert_email
}
