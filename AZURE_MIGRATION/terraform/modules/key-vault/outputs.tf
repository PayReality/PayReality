output "id" {
  value = azurerm_key_vault.this.id
}

output "name" {
  value = azurerm_key_vault.this.name
}

output "uri" {
  description = "Referenced by the Container App configuration (e.g. AZURE_KEY_VAULT_URI) so the application knows which vault to read from at startup."
  value       = azurerm_key_vault.this.vault_uri
}

output "application_secret_ids" {
  description = "Map of secret name -> Key Vault Secret resource ID, for the four Render-originated placeholder secrets. Consumed by modules/container-apps to build each secret's Key-Vault-backed environment variable reference."
  value       = { for name, secret in azurerm_key_vault_secret.application_secrets : name => secret.id }
}
