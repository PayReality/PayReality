variable "account_name" {
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

variable "deployment_name" {
  description = "The name the application refers to this deployment by (AZURE_AI_FOUNDRY_DEPLOYMENT_NAME). Kept separate from `model_name` since a deployment name is an operator choice, not the vendor's own model identifier."
  type        = string
  default     = "gpt-5-mini"
}

variable "model_name" {
  description = "The underlying model this deployment serves. gpt-5-mini by default: a genuinely production-ready structured-output model at pilot-appropriate cost -- see the module README's cost/model-choice rationale. (Originally gpt-4o-mini; switched during the first live staging apply, which failed with ServiceModelDeprecating -- confirmed via `az cognitiveservices account list-models` that gpt-4o-mini's only version no longer accepts new deployments, while gpt-5-mini is GenerallyAvailable in this account/region.)"
  type        = string
  default     = "gpt-5-mini"
}

variable "model_version" {
  type    = string
  default = "2025-08-07"
}

variable "sku_capacity" {
  description = "Tokens-per-minute capacity unit (thousands) for the model deployment. Small default appropriate for pilot-scale Authority Builder usage, not a production SLA commitment -- raise it once real usage data exists, the same reasoning modules/postgres already applies to its own sizing."
  type        = number
  default     = 10
}
