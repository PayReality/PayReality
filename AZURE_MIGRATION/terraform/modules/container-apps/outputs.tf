output "container_app_id" {
  value = azurerm_container_app.api.id
}

output "container_app_name" {
  value = azurerm_container_app.api.name
}

output "fqdn" {
  description = "The default *.azurecontainerapps.io hostname -- used for verification (Milestone 3) before any custom domain is bound (Milestone 9)."
  value       = azurerm_container_app.api.ingress[0].fqdn
}

output "environment_id" {
  value = azurerm_container_app_environment.this.id
}
