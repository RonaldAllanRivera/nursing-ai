locals {
  name           = "nursing-ai-${var.environment}"
  parameter_path = "/nursing-ai/${var.environment}"

  # Compute names its functions "<name>-api", "<name>-worker" and "<name>-ops". Ops makes the
  # log groups before the functions exist, so it needs the same names. A test
  # checks that the two agree.
  api_function_name    = "${local.name}-api"
  worker_function_name = "${local.name}-worker"
  ops_function_name    = "${local.name}-ops"

  # The custom domain goes live in the second apply (domain_validated): the first
  # only requests the certificate, because DNS is outside AWS and its record can't
  # exist yet.
  custom_domain_on = var.domain_name != null && var.domain_validated

  # The site's address: the custom domain once it is live, the CloudFront name
  # until then. The functions read the site-url parameter at cold start, so a
  # change takes effect at the next deploy (which restarts them).
  site_url = "https://${local.custom_domain_on ? var.domain_name : module.web.domain_name}"
}

# ---------------------------------------------------------------------------
# Custom domain (optional). DNS stays on Cloudflare, so there is no Route 53
# zone: Terraform outputs the two records to add by hand, in two applies.
# The certificate lives here, not in the web module: CloudFront reads
# certificates from us-east-1 only, and a module needing a second provider
# could not be validated on its own.
# ---------------------------------------------------------------------------

# ACM public certificates are free.
resource "aws_acm_certificate" "site" {
  provider = aws.us_east_1
  count    = var.domain_name == null ? 0 : 1

  domain_name       = var.domain_name
  validation_method = "DNS"

  # A replacement certificate must exist before the old one is released.
  lifecycle {
    create_before_destroy = true
  }
}

# Waits until ACM sees the validation record in DNS. It exists only in the second
# apply, after the record is added, so no apply waits for a record that isn't
# there yet.
resource "aws_acm_certificate_validation" "site" {
  provider = aws.us_east_1
  count    = local.custom_domain_on ? 1 : 0

  certificate_arn = aws_acm_certificate.site[0].arn
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

# Ops reads compute's API ID and queue name for its alarms and the web module's
# domain for the site-url parameter, and compute reads ops's log groups and
# parameters. Terraform orders the resources, not the
# modules, so the log groups still exist before the functions.
module "ops" {
  source = "../modules/ops"

  name                     = local.name
  parameter_path           = local.parameter_path
  alarm_email              = var.alert_email
  api_function_name        = local.api_function_name
  worker_function_name     = local.worker_function_name
  ops_function_name        = local.ops_function_name
  site_url                 = local.site_url
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

  site_url_parameter_arn               = module.ops.site_url_parameter_arn
  site_url_parameter_name              = module.ops.site_url_parameter_name
  bootstrap_admin_email_parameter_arn  = module.ops.bootstrap_admin_email_parameter_arn
  bootstrap_admin_email_parameter_name = module.ops.bootstrap_admin_email_parameter_name

  api_log_group_name       = module.ops.api_log_group_name
  worker_log_group_name    = module.ops.worker_log_group_name
  ops_log_group_name       = module.ops.ops_log_group_name
  api_access_log_group_arn = module.ops.api_access_log_group_arn
}

module "web" {
  source = "../modules/web"

  name = local.name

  custom_domain   = local.custom_domain_on ? var.domain_name : null
  certificate_arn = local.custom_domain_on ? aws_acm_certificate_validation.site[0].certificate_arn : null

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
