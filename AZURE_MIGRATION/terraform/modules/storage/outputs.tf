output "storage_account_id" {
  value = azurerm_storage_account.this.id
}

output "blob_service_id" {
  description = "The blob sub-resource, not the account itself -- Milestone 3 finding: a Storage Account's account-level diagnostic setting supports metrics only (no `enabled_log`/category groups; the API rejects even \"allLogs\" with a 400). Blob read/write/delete logging exists only at this sub-resource scope, so modules/diagnostics targets this, not storage_account_id, for the one target that actually needs log data (Evidence exports and uploads activity)."
  value       = "${azurerm_storage_account.this.id}/blobServices/default"
}

output "storage_account_name" {
  value = azurerm_storage_account.this.name
}

output "primary_blob_endpoint" {
  value = azurerm_storage_account.this.primary_blob_endpoint
}

output "uploads_container_name" {
  value = azurerm_storage_container.uploads.name
}

output "evidence_exports_container_name" {
  value = azurerm_storage_container.evidence_exports.name
}

output "authorization_receipts_container_name" {
  value = azurerm_storage_container.authorization_receipts.name
}
