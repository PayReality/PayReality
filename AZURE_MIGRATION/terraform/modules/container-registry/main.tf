# Standard SKU, not Premium: Premium's marginal features over Standard --
# geo-replication, Private Endpoints, and content-trust/retention
# policies -- have no current requirement behind them at this project's
# scale (a single-region deployment with one Container App pulling one
# image). Premium is named in docs/FUTURE_EXPANSION.md for if that
# changes; provisioning it now would be exactly the "unnecessary
# technology" this milestone's Absolute Rules forbid.
#
# admin_enabled = false deliberately: every pull/push happens through
# Azure AD (managed identity RBAC), never the registry's built-in admin
# username/password, which is itself a static credential this project's
# Identity Model exists specifically to avoid needing.

resource "azurerm_container_registry" "this" {
  name                = var.container_registry_name
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = "Standard"
  admin_enabled       = false

  tags = merge(var.tags, { Purpose = "Stores the PayReality API container image for ${var.environment}" })
}

resource "azurerm_role_assignment" "container_app_pull" {
  scope                = azurerm_container_registry.this.id
  role_definition_name = "AcrPull"
  principal_id         = var.container_app_identity_principal_id
}

resource "azurerm_role_assignment" "cicd_push" {
  scope                = azurerm_container_registry.this.id
  role_definition_name = "AcrPush"
  principal_id         = var.cicd_identity_principal_id
}
