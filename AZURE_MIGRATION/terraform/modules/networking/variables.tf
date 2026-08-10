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

variable "vnet_name" {
  type = string
}

variable "vnet_address_space" {
  description = "CIDR block(s) for the VNet. Default is deliberately outside the common 10.0.0.0/16 and 10.1.0.0/16 ranges to reduce collision risk if this VNet is ever peered with another network that used one of those defaults."
  type        = list(string)
  default     = ["10.20.0.0/16"]
}

variable "subnet_container_apps_name" {
  type = string
}

variable "subnet_container_apps_cidr" {
  description = "Sized /23 (510 usable addresses) rather than the /27 minimum Azure allows for a consumption-only Container Apps Environment, so a future move to workload profiles doesn't require re-addressing."
  type        = string
  default     = "10.20.0.0/23"
}

variable "subnet_postgres_name" {
  type = string
}

variable "subnet_postgres_cidr" {
  type    = string
  default = "10.20.2.0/24"
}

variable "subnet_private_endpoints_name" {
  type = string
}

variable "subnet_private_endpoints_cidr" {
  type    = string
  default = "10.20.3.0/24"
}
