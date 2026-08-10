variable "identity_name" {
  type = string
}

variable "cicd_identity_name" {
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

variable "github_repository" {
  description = "\"owner/repo\", e.g. \"PayReality/PayReality\" (confirmed as this repository's actual origin during the earlier Runtime Governance Migration work). Left blank (default) skips creating the federated credential entirely, so this module stays usable before a GitHub App/OIDC trust decision has been made."
  type        = string
  default     = ""
}

variable "github_deploy_branch" {
  description = "The single branch this environment's CI identity trusts. main for prod; a dedicated staging-deploy branch for staging -- never a wildcard."
  type        = string
  default     = "main"
}
