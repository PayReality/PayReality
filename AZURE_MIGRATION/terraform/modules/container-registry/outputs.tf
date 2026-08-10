output "id" {
  value = azurerm_container_registry.this.id
}

output "name" {
  value = azurerm_container_registry.this.name
}

output "login_server" {
  description = "The registry/ prefix for image references, e.g. used to compose var.container_image in the root module once Milestone 6 builds a real image."
  value       = azurerm_container_registry.this.login_server
}
