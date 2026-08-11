output "server_id" {
  value = azurerm_postgresql_flexible_server.this.id
}

output "server_name" {
  value = azurerm_postgresql_flexible_server.this.name
}

output "fqdn" {
  value = azurerm_postgresql_flexible_server.this.fqdn
}

output "database_name" {
  value = azurerm_postgresql_flexible_server_database.app.name
}

output "connection_string_secret_id" {
  description = "Full Key Vault Secret VERSIONLESS resource ID (not the value) -- what modules/container-apps' secret block actually needs. Versionless for the same reason as modules/key-vault's application_secret_ids output: a versioned ID pins the Container App to whatever version existed at the last apply, which defeats out-of-band rotation."
  value       = azurerm_key_vault_secret.connection_string.versionless_id
}
