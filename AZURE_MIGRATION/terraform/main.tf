# Root composition: wires the ten modules together. Every module call
# passes already-computed names (locals.tf) and cross-module references
# explicitly -- no module reaches for another module's internals, only
# its declared outputs.

module "resource_group" {
  source = "./modules/resource-group"

  name        = local.resource_group_name
  location    = var.location
  environment = var.environment
  tags        = local.common_tags
}

module "networking" {
  source = "./modules/networking"

  resource_group_name = module.resource_group.name
  location            = var.location
  environment         = var.environment
  tags                = local.common_tags

  vnet_name                     = local.vnet_name
  subnet_container_apps_name    = local.subnet_container_apps
  subnet_postgres_name          = local.subnet_postgres
  subnet_private_endpoints_name = local.subnet_private_endpoints
}

module "managed_identity" {
  source = "./modules/managed-identity"

  identity_name       = local.identity_container_app
  cicd_identity_name  = local.identity_cicd
  resource_group_name = module.resource_group.name
  location            = var.location
  environment         = var.environment
  tags                = local.common_tags

  github_repository    = var.github_repository
  github_deploy_branch = var.environment == "prod" ? "main" : "staging"
}

module "key_vault" {
  source = "./modules/key-vault"

  key_vault_name      = local.key_vault_name
  resource_group_name = module.resource_group.name
  location            = var.location
  environment         = var.environment
  tags                = local.common_tags

  private_endpoints_subnet_id         = module.networking.private_endpoints_subnet_id
  key_vault_private_dns_zone_id       = module.networking.key_vault_private_dns_zone_id
  container_app_identity_principal_id = module.managed_identity.principal_id
}

module "postgres" {
  source = "./modules/postgres"

  postgres_name       = local.postgres_name
  resource_group_name = module.resource_group.name
  location            = var.location
  environment         = var.environment
  tags                = local.common_tags

  vnet_id            = module.networking.vnet_id
  postgres_subnet_id = module.networking.postgres_subnet_id
  key_vault_id       = module.key_vault.id

  administrator_login          = var.postgres_administrator_login
  geo_redundant_backup_enabled = var.postgres_geo_redundant_backup_enabled
}

module "storage" {
  source = "./modules/storage"

  storage_account_name = local.storage_account_name
  resource_group_name  = module.resource_group.name
  location             = var.location
  environment          = var.environment
  tags                 = local.common_tags

  private_endpoints_subnet_id         = module.networking.private_endpoints_subnet_id
  blob_storage_private_dns_zone_id    = module.networking.blob_storage_private_dns_zone_id
  container_app_identity_principal_id = module.managed_identity.principal_id
  replication_type                    = var.storage_replication_type
}

module "container_registry" {
  source = "./modules/container-registry"

  container_registry_name = local.container_registry_name
  resource_group_name     = module.resource_group.name
  location                = var.location
  environment             = var.environment
  tags                    = local.common_tags

  container_app_identity_principal_id = module.managed_identity.principal_id
  cicd_identity_principal_id          = module.managed_identity.cicd_principal_id
}

module "monitoring" {
  source = "./modules/monitoring"

  log_analytics_name  = local.log_analytics_name
  app_insights_name   = local.app_insights_name
  resource_group_name = module.resource_group.name
  location            = var.location
  environment         = var.environment
  tags                = local.common_tags
}

module "container_apps" {
  source = "./modules/container-apps"

  container_apps_environment_name = local.container_apps_env_name
  container_app_name              = local.container_app_name
  resource_group_name             = module.resource_group.name
  location                        = var.location
  environment                     = var.environment
  tags                            = local.common_tags

  container_apps_subnet_id   = module.networking.container_apps_subnet_id
  log_analytics_workspace_id = module.monitoring.log_analytics_workspace_id
  container_app_identity_id  = module.managed_identity.id

  database_url_secret_id = module.postgres.connection_string_secret_id
  application_secret_ids = module.key_vault.application_secret_ids

  container_image = var.container_image
  cors_origin     = var.environment == "prod" ? "https://payreality.aisecurewatch.com" : "https://staging.payreality.aisecurewatch.com"
  owner_email     = var.owner
  min_replicas    = var.container_apps_min_replicas
}

module "diagnostics" {
  source = "./modules/diagnostics"

  log_analytics_workspace_id = module.monitoring.log_analytics_workspace_id

  targets = {
    postgres           = module.postgres.server_id
    key-vault          = module.key_vault.id
    storage            = module.storage.storage_account_id
    container-apps-env = module.container_apps.environment_id
    container-registry = module.container_registry.id
  }
}
