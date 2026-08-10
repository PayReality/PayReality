variable "container_registry_name" {
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
  description = "Granted AcrPull only -- the running application pulls images, it never pushes them."
  type        = string
}

variable "cicd_identity_principal_id" {
  description = "Granted AcrPush -- CI pushes images, it never runs as the application."
  type        = string
}
