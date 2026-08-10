output "id" {
  value = azurerm_user_assigned_identity.container_app.id
}

output "principal_id" {
  description = "Azure AD object ID -- what gets granted a role assignment (e.g. `azurerm_role_assignment.principal_id`)."
  value       = azurerm_user_assigned_identity.container_app.principal_id
}

output "client_id" {
  description = "What the application/Container App configuration references at runtime to authenticate as this identity."
  value       = azurerm_user_assigned_identity.container_app.client_id
}

output "name" {
  value = azurerm_user_assigned_identity.container_app.name
}

output "cicd_principal_id" {
  description = "Granted AcrPush (modules/container-registry) and, in a future milestone, Container Apps deploy permissions. Never granted Key Vault or Storage access -- see this module's README."
  value       = azurerm_user_assigned_identity.cicd.principal_id
}

output "cicd_client_id" {
  description = "Referenced by the future GitHub Actions workflow's azure/login step (Milestone 6+), not used anywhere in this milestone."
  value       = azurerm_user_assigned_identity.cicd.client_id
}

output "cicd_name" {
  value = azurerm_user_assigned_identity.cicd.name
}
