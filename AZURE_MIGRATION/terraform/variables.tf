# Every variable here is either required (no default -- must be supplied
# by an environment .tfvars file, see environments/) or a genuinely safe,
# documented default. None is a secret: secret values never pass through
# a Terraform variable (see ../docs/IDENTITY_MODEL.md's secret lifecycle
# section) -- application secrets are created empty in Key Vault by this
# project and populated out-of-band, by Milestone 5, never by `terraform
# apply` carrying a plaintext value in state.

variable "environment" {
  description = "Deployment environment. Restricted to the two cloud environments Sprint 1's Infrastructure Blueprint actually calls for -- local and development stay on docker-compose by that same document's own decision, and never get a Terraform environment."
  type        = string

  validation {
    condition     = contains(["staging", "prod"], var.environment)
    error_message = "environment must be exactly \"staging\" or \"prod\"."
  }
}

variable "location" {
  description = "Azure region for every resource in this project. Milestone 3 finding: this specific subscription is restricted from provisioning PostgreSQL Flexible Server in eastus2, eastus, westus2, and westeurope (\"Subscriptions are restricted from provisioning in this region\" -- a new-subscription capacity restriction, confirmed directly via `az postgres flexible-server list-skus`, not a Terraform or code defect). centralus has no such restriction for this subscription and is the default for that reason -- see AZURE_MIGRATION/MILESTONE_3_DEPLOYMENT_REPORT.md."
  type        = string
  default     = "centralus"
}

variable "location_short" {
  description = "Short region code used in resource names (see docs/NAMING_CONVENTION.md). Must be kept in sync with `location` by whoever changes it -- not derived automatically, since Azure's region-name-to-abbreviation mapping is a naming convention choice, not a fact Terraform can look up."
  type        = string
  default     = "cus"
}

variable "owner" {
  description = "Tag value identifying who is accountable for this environment's resources (a person or team identifier, e.g. an email address)."
  type        = string
}

variable "cost_center" {
  description = "Tag value for cost allocation. A single-value default is intentional at this company's current size (see docs/TAGGING_STRATEGY.md) -- override per environment only if a real second cost center exists."
  type        = string
  default     = "engineering"
}

variable "postgres_administrator_login" {
  description = "PostgreSQL Flexible Server administrator username. Not a secret itself, but paired with a generated password never stored in Terraform state (see modules/postgres/README.md)."
  type        = string
  default     = "payreality_admin"
}

variable "postgres_geo_redundant_backup_enabled" {
  description = "true for prod (survives a full regional outage), false for staging -- see modules/postgres/README.md. Set per environment in environments/*.tfvars, never hardcoded here."
  type        = bool
  default     = false
}

variable "storage_replication_type" {
  description = "GRS for prod, LRS for staging -- same reasoning as postgres_geo_redundant_backup_enabled, above."
  type        = string
  default     = "LRS"
}

variable "container_apps_min_replicas" {
  description = "1 (always warm) for prod; staging may set 0 to save cost since it isn't customer-facing."
  type        = number
  default     = 1
}

variable "github_repository" {
  description = "\"owner/repo\" for GitHub Actions OIDC federation (modules/managed-identity). Left blank (default) skips creating the federated credential entirely."
  type        = string
  default     = ""
}

variable "container_image" {
  description = "Full image reference (registry/repository:tag) the Container App should run. Left as a variable, not a hardcoded value, because this changes on every deploy -- Milestone 2 provisions the Container App with a placeholder; Milestone 6 is what actually points it at a real, built image."
  type        = string
  default     = "mcr.microsoft.com/k8se/quickstart:latest" # a public, harmless placeholder image so `terraform apply` succeeds before Milestone 6 exists -- swapped for the real image explicitly in Milestone 6, never assumed here.
}

variable "alert_notification_email" {
  description = "Milestone 5: where every azurerm_monitor_action_group in modules/alerts sends notifications. No default -- closing MILESTONE_4_RISK_REGISTER.md's #1 finding (zero alerts, nothing pages anyone) means every environment must consciously set a real recipient, not inherit a placeholder."
  type        = string
}
