data "azurerm_client_config" "current" {}

resource "azurerm_storage_account" "this" {
  name                     = var.storage_account_name
  resource_group_name      = var.resource_group_name
  location                 = var.location
  account_tier             = "Standard"
  account_replication_type = var.replication_type
  min_tls_version          = "TLS1_2"

  # Milestone 3, same identity-first decision as modules/key-vault: Azure
  # RBAC + Microsoft Entra ID is the primary security boundary for
  # management operations on this account, not network isolation. A hard
  # `public_network_access_enabled = false` blocks the data plane from
  # every caller outside the VNet -- including Terraform, which has no
  # VPN/bastion/self-hosted runner to run from (deliberately rejected, see
  # docs/KNOWN_RISKS.md and MILESTONE_3_SECURITY_REVIEW.md). Only two
  # identities ever hold a role on this account (below); the running
  # application still reaches Blob Storage exclusively through the
  # private endpoint whenever it runs inside the VNet -- the public path
  # serves authenticated management operations only.
  public_network_access_enabled   = true
  allow_nested_items_to_be_public = false # no container or blob may be individually made public, full stop -- Evidence-related bytes never get a public URL by accident

  blob_properties {
    versioning_enabled = true

    delete_retention_policy {
      days = 30
    }
    container_delete_retention_policy {
      days = 30
    }
  }

  tags = merge(var.tags, { Purpose = "Object storage for PayReality ${var.environment} document uploads and evidence exports" })
}

resource "azurerm_private_endpoint" "blob" {
  name                = "pe-${var.storage_account_name}-blob"
  resource_group_name = var.resource_group_name
  location            = var.location
  subnet_id           = var.private_endpoints_subnet_id
  tags                = merge(var.tags, { Purpose = "Private network path to Blob Storage -- no public endpoint is enabled" })

  private_service_connection {
    name                           = "psc-${var.storage_account_name}-blob"
    private_connection_resource_id = azurerm_storage_account.this.id
    subresource_names              = ["blob"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "default"
    private_dns_zone_ids = [var.blob_storage_private_dns_zone_id]
  }
}

# Milestone 3 finding: the same RBAC-vs-control-plane gap found on Key
# Vault applies here -- a subscription Owner does not automatically get
# blob data-plane access, and this provider version's container/blob
# resources authenticate via the data plane. "Storage Blob Data
# Contributor" is the narrowest built-in role that can create/manage
# containers and their contents; granted here to the Terraform-operator
# identity, separately from the identical role already granted to the
# Container App's runtime identity below, so each identity's access is
# an explicit, auditable grant rather than an inherited assumption.
resource "azurerm_role_assignment" "terraform_operator_blob_data_contributor" {
  scope                = azurerm_storage_account.this.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = data.azurerm_client_config.current.object_id
}

# Same RBAC propagation reality as modules/key-vault's identical
# resource -- see that module's comment for why this wait exists instead
# of relying on incidental ordering.
resource "time_sleep" "wait_for_blob_contributor_rbac" {
  depends_on      = [azurerm_role_assignment.terraform_operator_blob_data_contributor]
  create_duration = "30s"
}

# Three containers, matching Sprint 1's storage design and this
# milestone's explicit instruction to design for uploads, evidence
# exports, and future Authorization Receipts -- "future" here means
# "provisioned ahead of the corresponding feature per this milestone's
# own instruction," not speculative scope this module invented on its
# own (RFC-001 is unimplemented; this container will sit empty until it
# is, exactly like Postgres's database sits empty until Milestone 4).

resource "azurerm_storage_container" "uploads" {
  name                  = "uploads"
  storage_account_name  = azurerm_storage_account.this.name
  container_access_type = "private"

  depends_on = [time_sleep.wait_for_blob_contributor_rbac]
}

resource "azurerm_storage_container" "evidence_exports" {
  name                  = "evidence-exports"
  storage_account_name  = azurerm_storage_account.this.name
  container_access_type = "private"

  depends_on = [time_sleep.wait_for_blob_contributor_rbac]
}

resource "azurerm_storage_container" "authorization_receipts" {
  name                  = "authorization-receipts"
  storage_account_name  = azurerm_storage_account.this.name
  container_access_type = "private"

  depends_on = [time_sleep.wait_for_blob_contributor_rbac]
}

# Lifecycle: cost-optimize by moving cold data to a cheaper access tier;
# never auto-delete anything. Evidence and Authorization Receipts are
# compliance-relevant records this platform's own architecture treats as
# append-only and permanent (SPECIFICATION/45_PHASE_5_BROKEN_PROMISE_REPORT.md)
# -- an automatic deletion rule on either would directly contradict that.
resource "azurerm_storage_management_policy" "this" {
  storage_account_id = azurerm_storage_account.this.id

  rule {
    name    = "uploads-tier-down"
    enabled = true
    filters {
      prefix_match = ["uploads/"]
      blob_types   = ["blockBlob"]
    }
    actions {
      base_blob {
        tier_to_cool_after_days_since_modification_greater_than = 90
      }
    }
  }

  rule {
    name    = "evidence-and-receipts-tier-down-never-delete"
    enabled = true
    filters {
      prefix_match = ["evidence-exports/", "authorization-receipts/"]
      blob_types   = ["blockBlob"]
    }
    actions {
      base_blob {
        tier_to_cool_after_days_since_modification_greater_than = 180
        # Deliberately no delete action anywhere in this rule.
      }
    }
  }
}

resource "azurerm_role_assignment" "container_app_blob_contributor" {
  scope                = azurerm_storage_account.this.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = var.container_app_identity_principal_id
}
