output "log_analytics_workspace_id" {
  value = azurerm_log_analytics_workspace.this.id
}

output "log_analytics_workspace_name" {
  value = azurerm_log_analytics_workspace.this.name
}

output "app_insights_id" {
  value = azurerm_application_insights.this.id
}

output "app_insights_connection_string" {
  description = "Not treated as a secret by Azure (it's designed to be embedded in client-side telemetry SDKs), but still passed as a Terraform output rather than hardcoded, since it's environment-specific."
  value       = azurerm_application_insights.this.connection_string
}
