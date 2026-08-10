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
  description = "Full Key Vault Secret resource ID (not the value) -- what modules/container-apps' secret block actually needs."
  value       = azurerm_key_vault_secret.connection_string.id
}
