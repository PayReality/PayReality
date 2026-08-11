variable "search_service_name" {
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

variable "container_app_identity_principal_id" {
  type = string
}

variable "sku" {
  description = "\"basic\" by default: the cheapest tier that supports Azure RBAC data-plane authentication (the free tier's AAD-auth support is inconsistent across regions/API versions) -- see the module README."
  type        = string
  default     = "basic"
}
