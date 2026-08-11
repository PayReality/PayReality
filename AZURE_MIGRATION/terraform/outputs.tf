output "resource_group_name" {
  value = module.resource_group.name
}

output "container_app_fqdn" {
  description = "Default *.azurecontainerapps.io hostname -- the URL Milestone 3's verification actually curls, before any DNS cutover."
  value       = module.container_apps.fqdn
}

output "container_registry_login_server" {
  value = module.container_registry.login_server
}

output "postgres_fqdn" {
  value = module.postgres.fqdn
}

output "storage_account_name" {
  value = module.storage.storage_account_name
}

output "key_vault_uri" {
  value = module.key_vault.uri
}

output "log_analytics_workspace_name" {
  value = module.monitoring.log_analytics_workspace_name
}

output "cicd_identity_client_id" {
  description = "For the future GitHub Actions workflow's azure/login step (not used this milestone)."
  value       = module.managed_identity.cicd_client_id
}

output "monitoring_dashboard_url" {
  value = module.dashboard.portal_url
}

output "alert_action_group_name" {
  value = module.alerts.action_group_name
}
