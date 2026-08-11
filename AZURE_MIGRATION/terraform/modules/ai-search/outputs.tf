output "endpoint" {
  description = "Consumed as AZURE_AI_SEARCH_ENDPOINT -- app/services/authority_intelligence_service.py reads this directly, no Key Vault involved (not a credential; RBAC is)."
  value       = "https://${azurerm_search_service.this.name}.search.windows.net"
}

output "id" {
  value = azurerm_search_service.this.id
}

output "name" {
  value = azurerm_search_service.this.name
}
