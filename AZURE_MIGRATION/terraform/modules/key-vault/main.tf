data "azurerm_client_config" "current" {}

# RBAC authorization model, not the legacy access-policy model -- Key
# Vault access is granted the same way every other Azure resource's
# access is granted in this project (azurerm_role_assignment), one
# consistent permission model instead of two.
#
# Deliberately empty of secrets: this module provisions the vault and
# its access model only. Populating real secret values is Milestone 5's
# job, not this one -- see docs/IDENTITY_MODEL.md's secret lifecycle
# section for why that boundary is deliberate, not a gap.

resource "azurerm_key_vault" "this" {
  name                = var.key_vault_name
  resource_group_name = var.resource_group_name
  location            = var.location
  tenant_id           = data.azurerm_client_config.current.tenant_id
  sku_name            = "standard"

  enable_rbac_authorization     = true
  purge_protection_enabled      = true # a deleted secret's key material (e.g. the Evidence signing key) must never be purgeable within its retention window -- see docs/KNOWN_RISKS.md
  soft_delete_retention_days    = 90
  public_network_access_enabled = false

  network_acls {
    default_action = "Deny"
    bypass         = "AzureServices"
  }

  tags = merge(var.tags, { Purpose = "Owns every PayReality ${var.environment} secret value" })
}

resource "azurerm_private_endpoint" "key_vault" {
  name                = "pe-${var.key_vault_name}"
  resource_group_name = var.resource_group_name
  location            = var.location
  subnet_id           = var.private_endpoints_subnet_id
  tags                = merge(var.tags, { Purpose = "Private network path to Key Vault -- no public endpoint is enabled" })

  private_service_connection {
    name                           = "psc-${var.key_vault_name}"
    private_connection_resource_id = azurerm_key_vault.this.id
    subresource_names              = ["vault"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "default"
    private_dns_zone_ids = [var.key_vault_private_dns_zone_id]
  }
}

# The Container App's managed identity may read (never manage/delete)
# secrets -- the narrowest built-in role that satisfies "the app can read
# its own secrets at startup" without also granting it the ability to
# create or rotate them, which stays a human/CI action.
resource "azurerm_role_assignment" "container_app_secrets_user" {
  scope                = azurerm_key_vault.this.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = var.container_app_identity_principal_id
}

# Placeholder secrets for the four values that come from Render's
# existing production environment, not from anything Terraform generates
# (contrast with modules/postgres, which creates its own secrets because
# Terraform itself is the origin of that value). Deliberately NOT
# populated with real values here: "Secrets should never live inside
# Terraform variables" (Milestone 2's own Identity instruction) means the
# real EVIDENCE_SIGNING_KEY_B64/ADMIN_API_KEY/etc. values must never pass
# through a `-var` or a `.tfvars` file just to reach this resource.
#
# Milestone 5's actual mechanism is `az keyvault secret set` (or the
# Azure Portal), run directly against these four secret names, reading
# the real value from Render's environment out-of-band -- never a
# `terraform apply` carrying the value. `ignore_changes` on `value`
# exists specifically so that once Milestone 5 sets the real value, a
# later, unrelated `terraform apply` (e.g. Milestone 8's monitoring work)
# can never silently stomp it back to this placeholder.
resource "azurerm_key_vault_secret" "application_secrets" {
  for_each = toset([
    "evidence-signing-key-b64",
    "evidence-signing-key-id",
    "admin-api-key",
    "anthropic-api-key",
  ])

  name         = each.value
  value        = "PENDING-MILESTONE-5-MANUAL-ENTRY"
  key_vault_id = azurerm_key_vault.this.id

  tags = merge(var.tags, { Purpose = "Placeholder for a secret migrated from Render in Milestone 5 -- value set out-of-band, never via Terraform" })

  lifecycle {
    ignore_changes = [value]
  }
}
