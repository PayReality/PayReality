variable "postgres_name" {
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

variable "vnet_id" {
  type = string
}

variable "postgres_subnet_id" {
  type = string
}

variable "key_vault_id" {
  type = string
}

variable "administrator_login" {
  type = string
}

variable "database_name" {
  description = "The single application database name inside the server."
  type        = string
  default     = "payreality"
}

variable "sku_name" {
  description = "Burstable B1ms by default -- sized to today's pilot-scale traffic (see AZURE_MIGRATION/MILESTONE_1_DISCOVERY.md), not to a hypothetical enterprise load. Change this variable, not the module, when real usage data justifies a larger tier."
  type        = string
  default     = "B_Standard_B1ms"
}

variable "storage_mb" {
  type    = number
  default = 32768 # 32 GiB -- Flexible Server's smallest generally-available size, ample for today's data volume including uploaded-document bytes (see docs/OPERATIONAL_ASSUMPTIONS.md)
}

variable "backup_retention_days" {
  description = "7-35. Defaulted to the maximum: backups are one of the cheapest resources in this entire project relative to what they protect (see Sprint 1's Backup & Disaster Recovery Plan), so there's no cost reason to retain less than the maximum Azure allows."
  type        = number
  default     = 35
}

variable "geo_redundant_backup_enabled" {
  description = "Recommended true for prod, false for staging (set per-environment in environments/*.tfvars, not hardcoded here) -- staging's data is disposable and re-seedable, so paying for geo-redundant backup of it has no matching benefit."
  type        = bool
  default     = false
}

variable "high_availability_enabled" {
  description = "Zone-redundant HA. Defaulted off for both environments today -- named as a real, well-understood future-expansion option (docs/FUTURE_EXPANSION.md), not built ahead of a demonstrated availability requirement this platform doesn't have yet (its own application layer is already fail-closed by construction; HA protects against a different, infrastructure-level failure mode that hasn't been the actual cause of any incident so far)."
  type        = bool
  default     = false
}
