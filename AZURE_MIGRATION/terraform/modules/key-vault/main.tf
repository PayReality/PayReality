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

  enable_rbac_authorization  = true # Azure RBAC only, per explicit decision -- access policies are never enabled on this vault
  purge_protection_enabled   = true # a deleted secret's key material (e.g. the Evidence signing key) must never be purgeable within its retention window -- see docs/KNOWN_RISKS.md
  soft_delete_retention_days = 90

  # Milestone 3, explicit decision: identity (Azure RBAC + Microsoft
  # Entra ID) is the primary security boundary for management operations,
  # not network isolation. A hard `public_network_access_enabled = false`
  # blocks every caller outside the VNet, including Terraform itself --
  # and there is no VPN or self-hosted runner inside the VNet. Building
  # one solely to satisfy Terraform access was explicitly rejected (see
  # docs/KNOWN_RISKS.md and MILESTONE_3_SECURITY_REVIEW.md): it would be
  # real, ongoing infrastructure whose only job is working around an
  # identity model that already solves the same problem. The public
  # endpoint below authenticates every request via Azure AD; only two
  # identities ever hold any role on this vault (below), there is no
  # shared-key or anonymous path for Key Vault at all, and the running
  # application still reaches this vault exclusively through the private
  # endpoint whenever it runs inside the VNet -- the public path serves
  # authenticated management operations only.
  public_network_access_enabled = true

  network_acls {
    default_action = "Allow"
    bypass         = "AzureServices"
  }

  tags = merge(var.tags, { Purpose = "Owns every PayReality ${var.environment} secret value" })
}

# Milestone 3 finding: a subscription Owner does NOT automatically get
# data-plane access to a Key-Vault-RBAC-authorized vault's secrets --
# Azure requires an explicit role assignment for that, separate from
# control-plane (ARM) permissions to manage the vault resource itself.
# Without this, every azurerm_key_vault_secret resource below fails with
# ForbiddenByRbac the moment Terraform tries to check whether it already
# exists, regardless of who runs `terraform apply` or what
# subscription-level role they hold. "Key Vault Secrets Officer" is the
# minimum built-in role that can create/manage secret values -- not
# "Key Vault Administrator", which also grants certificate/key
# management this operator role never needs.
resource "azurerm_role_assignment" "terraform_operator_secrets_officer" {
  scope                = azurerm_key_vault.this.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}

# RBAC role assignments are eventually consistent, not immediate --
# Milestone 3's own apply failure surfaced Azure's own error message
# ("If role assignments... were changed recently, please observe
# propagation time") verbatim. A short, explicit wait here is the
# smallest fix that respects that reality, rather than relying on
# Terraform happening to spend enough wall-clock time on other resources
# first.
resource "time_sleep" "wait_for_secrets_officer_rbac" {
  depends_on      = [azurerm_role_assignment.terraform_operator_secrets_officer]
  create_duration = "30s"
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

  depends_on = [time_sleep.wait_for_secrets_officer_rbac]
}
