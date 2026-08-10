# The single source of truth for naming and tagging (docs/NAMING_CONVENTION.md,
# docs/TAGGING_STRATEGY.md). Every module receives a fully-formed name and
# a tags map as input variables; no module invents its own naming logic.
# This is what "one predictable naming strategy" means in practice: one
# place that computes names, everywhere else just consumes them.

locals {
  app_name       = "payreality"
  app_name_short = "pr" # used only for the three globally-unique, character-restricted resources below

  # Human-readable, hyphenated names -- generous Azure length limits (63-90 chars) for these resource types.
  resource_group_name      = "rg-${local.app_name}-${var.environment}-${var.location_short}"
  vnet_name                = "vnet-${local.app_name}-${var.environment}-${var.location_short}"
  subnet_container_apps    = "snet-${local.app_name}-containerapps-${var.environment}-${var.location_short}"
  subnet_postgres          = "snet-${local.app_name}-postgres-${var.environment}-${var.location_short}"
  subnet_private_endpoints = "snet-${local.app_name}-privateendpoints-${var.environment}-${var.location_short}"
  container_apps_env_name  = "cae-${local.app_name}-${var.environment}-${var.location_short}"
  container_app_name       = "ca-${local.app_name}-api-${var.environment}-${var.location_short}"
  postgres_name            = "psql-${local.app_name}-${var.environment}-${var.location_short}"
  identity_container_app   = "id-${local.app_name}-containerapp-${var.environment}-${var.location_short}"
  identity_cicd            = "id-${local.app_name}-cicd-${var.environment}-${var.location_short}"
  log_analytics_name       = "log-${local.app_name}-${var.environment}-${var.location_short}"
  app_insights_name        = "appi-${local.app_name}-${var.environment}-${var.location_short}"

  # Globally-unique, character-restricted names (lowercase alphanumeric
  # only, no hyphens, <=24 chars) -- a short random suffix is the only
  # thing making these unique across every Azure customer, not a
  # convention choice, so it's isolated to exactly these three.
  key_vault_name          = "kv-${local.app_name_short}-${var.environment}-${random_string.suffix.result}"
  storage_account_name    = "st${local.app_name_short}${var.environment}${random_string.suffix.result}"
  container_registry_name = "acr${local.app_name_short}${var.environment}${random_string.suffix.result}"

  common_tags = {
    Environment = var.environment
    Application = "PayReality"
    Owner       = var.owner
    CostCenter  = var.cost_center
    ManagedBy   = "Terraform"
    Version     = "milestone-2"
    CreatedBy   = "azure-migration-program"
  }
}

resource "random_string" "suffix" {
  length  = 4
  special = false
  upper   = false
  numeric = true
}
