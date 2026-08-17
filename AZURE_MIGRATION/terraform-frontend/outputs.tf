output "website_default_hostname" {
  value = azurerm_static_web_app.website.default_host_name
}

output "dashboard_default_hostname" {
  value = azurerm_static_web_app.dashboard.default_host_name
}

# Deliberately sensitive: this is the deployment credential GitHub
# Actions authenticates with, equivalent in blast radius to a deploy key.
output "website_api_key" {
  value     = azurerm_static_web_app.website.api_key
  sensitive = true
}

output "dashboard_api_key" {
  value     = azurerm_static_web_app.dashboard.api_key
  sensitive = true
}
