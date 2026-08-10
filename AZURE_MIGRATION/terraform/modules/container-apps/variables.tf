variable "container_apps_environment_name" {
  type = string
}

variable "container_app_name" {
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

variable "container_apps_subnet_id" {
  type = string
}

variable "log_analytics_workspace_id" {
  type = string
}

variable "container_app_identity_id" {
  description = "Full resource ID (not principal_id) -- required by both the `identity` block and every `secret`'s `identity` argument."
  type        = string
}

variable "database_url_secret_id" {
  description = "Key Vault Secret resource ID from modules/postgres."
  type        = string
}

variable "application_secret_ids" {
  description = "Map of secret name -> Key Vault Secret resource ID, from modules/key-vault's application_secret_ids output."
  type        = map(string)
}

variable "container_image" {
  type = string
}

variable "container_port" {
  type    = number
  default = 8000 # matches server/Dockerfile's EXPOSE 8000, confirmed directly
}

variable "cpu" {
  description = "vCPU allocated to the single container. 0.5 is proportionate to today's pilot-scale traffic (AZURE_MIGRATION/MILESTONE_1_DISCOVERY.md) -- a variable, not hardcoded, so it can change without a module edit once real load data exists."
  type        = number
  default     = 0.5
}

variable "memory" {
  type    = string
  default = "1Gi"
}

variable "min_replicas" {
  description = "1 by default -- always warm, no cold-start latency. Staging may override to 0 in environments/staging.tfvars to save cost, since staging is not customer-facing."
  type        = number
  default     = 1
}

variable "max_replicas" {
  description = "3 by default. Horizontal scaling beyond this is explicitly gated on resolving the in-process rate limiter first -- see AZURE_MIGRATION/MILESTONE_1_DISCOVERY.md risk notes and Sprint 1's own T12 (deferred). Raising this number without that fix would silently under-count rate limits the moment more than one replica is actually running."
  type        = number
  default     = 3
}

variable "http_scale_concurrent_requests" {
  type    = string
  default = "50"
}

variable "cors_origin" {
  type = string
}

variable "intent_signature_window_seconds" {
  type    = number
  default = 300
}

variable "organization_name" {
  type    = string
  default = "PayReality"
}

variable "owner_email" {
  type = string
}
