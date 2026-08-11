output "endpoint" {
  description = "Consumed as AZURE_AI_FOUNDRY_ENDPOINT -- the Container App's app/domain/ai_provider/azure_foundry_provider.py reads this directly, no Key Vault involved (not a credential)."
  value       = azurerm_cognitive_account.this.endpoint
}

output "deployment_name" {
  value = azurerm_cognitive_deployment.this.name
}

output "id" {
  value = azurerm_cognitive_account.this.id
}
