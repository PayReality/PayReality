variable "storage_account_name" {
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

variable "blob_storage_private_dns_zone_id" {
  type = string
}

variable "container_app_identity_principal_id" {
  type = string
}

variable "replication_type" {
  description = "GRS for prod (survives a full regional outage), LRS is an acceptable, cheaper choice for staging -- set per environment in environments/*.tfvars, not hardcoded here."
  type        = string
  default     = "LRS"
}
