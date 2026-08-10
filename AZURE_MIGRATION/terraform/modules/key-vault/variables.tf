variable "key_vault_name" {
  type = string
}

variable "resource_group_name" {
  type = string
}

variable "location" {
  type = string
}

variable "environment" {
  type = string
}

variable "tags" {
  type = map(string)
}

variable "private_endpoints_subnet_id" {
  type = string
}

variable "key_vault_private_dns_zone_id" {
  type = string
}

variable "container_app_identity_principal_id" {
  description = "Principal ID of the Container App's user-assigned managed identity (from modules/managed-identity), granted Key Vault Secrets User on this vault."
  type        = string
}
