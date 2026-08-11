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

variable "container_app_id" {
  type = string
}

variable "postgres_id" {
  type = string
}

variable "key_vault_id" {
  type = string
}

variable "container_app_name" {
  type = string
}

variable "postgres_name" {
  type = string
}

variable "key_vault_name" {
  type = string
}
