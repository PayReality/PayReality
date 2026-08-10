resource "azurerm_storage_account" "this" {
  name                     = var.storage_account_name
  resource_group_name      = var.resource_group_name
  location                 = var.location
  account_tier             = "Standard"
  account_replication_type = var.replication_type
  min_tls_version          = "TLS1_2"

  public_network_access_enabled   = false
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
}

resource "azurerm_storage_container" "evidence_exports" {
  name                  = "evidence-exports"
  storage_account_name  = azurerm_storage_account.this.name
  container_access_type = "private"
}

resource "azurerm_storage_container" "authorization_receipts" {
  name                  = "authorization-receipts"
  storage_account_name  = azurerm_storage_account.this.name
  container_access_type = "private"
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
