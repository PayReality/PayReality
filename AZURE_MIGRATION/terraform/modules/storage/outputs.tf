output "storage_account_id" {
  value = azurerm_storage_account.this.id
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
