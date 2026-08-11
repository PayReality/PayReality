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
  #
  # Key Vault deliberately draws from its OWN random_string
  # (key_vault_suffix), not the one shared by Storage/Container Registry.
  # Milestone 3 finding: a Key Vault name is not freely reusable the way
  # a Storage Account or ACR name is -- soft delete plus purge protection
  # (both on by design here, to protect the eventual Evidence signing
  # key) can leave a name permanently reserved for up to 90 days after
  # the vault itself is gone, as happened to kv-pr-staging-adzg (see
  # MILESTONE_3_DEPLOYMENT_REPORT.md). A dedicated, higher-entropy (6
  # rather than 4 characters) suffix, generated independently per
  # environment, is this project's standing collision-resistance
  # strategy for Key Vault specifically -- not a one-off rename -- so a
  # future rebuild of staging, prod, or any new environment draws a
  # fresh name rather than risking a repeat collision with a still-
  # reserved one.
  key_vault_name          = "kv-${local.app_name_short}-${var.environment}-${random_string.key_vault_suffix.result}"
  storage_account_name    = "st${local.app_name_short}${var.environment}${random_string.suffix.result}"
  container_registry_name = "acr${local.app_name_short}${var.environment}${random_string.suffix.result}"

  # Authority Intelligence Program, Phase 1. ai_foundry_account_name
  # draws from its own dedicated suffix, not the shared one, for the
  # same reason key_vault_name does: Cognitive Services accounts (the
  # resource type backing Azure AI Foundry) support soft-delete, which
  # can leave a name reserved for a retention period after deletion --
  # exactly the trap Milestone 3 already hit and fixed for Key Vault.
  # Search service names have no such trap (deletion is immediate, no
  # soft-delete concept for the service resource), so ai_search_service_name
  # safely shares the same suffix Storage/ACR already use.
  ai_foundry_account_name = "aif-${local.app_name_short}-${var.environment}-${random_string.ai_foundry_suffix.result}"
  ai_search_service_name  = "srch-${local.app_name_short}-${var.environment}-${random_string.suffix.result}"

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

# Deliberately separate from random_string.suffix above -- see the
# key_vault_name comment for why Key Vault needs its own, higher-entropy,
# independently-drawn suffix rather than sharing one with Storage/ACR.
# 6 lowercase alphanumeric characters: still well within Key Vault's
# 24-character name limit alongside "kv-pr-<environment>-", and a wider
# character set (letters + digits, not digits-only) than the shared
# 4-digit suffix, for meaningfully lower collision odds on the one
# resource where a collision costs a 90-day naming lockout instead of a
# harmless retry.
resource "random_string" "key_vault_suffix" {
  length  = 6
  special = false
  upper   = false
  numeric = true
}

# See ai_foundry_account_name's comment above for why this is separate
# from both random_string.suffix and random_string.key_vault_suffix.
resource "random_string" "ai_foundry_suffix" {
  length  = 6
  special = false
  upper   = false
  numeric = true
}
