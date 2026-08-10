output "vnet_id" {
  value = azurerm_virtual_network.this.id
}

output "vnet_name" {
  value = azurerm_virtual_network.this.name
}

output "container_apps_subnet_id" {
  value = azurerm_subnet.container_apps.id
}

output "postgres_subnet_id" {
  value = azurerm_subnet.postgres.id
}

output "private_endpoints_subnet_id" {
  value = azurerm_subnet.private_endpoints.id
}

output "key_vault_private_dns_zone_id" {
  value = azurerm_private_dns_zone.key_vault.id
}

output "key_vault_private_dns_zone_name" {
  value = azurerm_private_dns_zone.key_vault.name
}

output "blob_storage_private_dns_zone_id" {
  value = azurerm_private_dns_zone.blob_storage.id
}

output "blob_storage_private_dns_zone_name" {
  value = azurerm_private_dns_zone.blob_storage.name
}
