output "id" {
  value = azurerm_portal_dashboard.this.id
}

output "portal_url" {
  description = "Direct link to view this dashboard in the Azure Portal."
  value       = "https://portal.azure.com/#@/dashboard/arm${azurerm_portal_dashboard.this.id}"
}
