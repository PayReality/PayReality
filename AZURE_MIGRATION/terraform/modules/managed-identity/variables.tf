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

variable "github_repository_immutable" {
  description = <<-EOT
    "owner@ownerId/repo@repoId", GitHub's immutable-subject-claim format
    (github.blog/changelog/2026-04-23-immutable-subject-claims-for-github-actions-oidc-tokens),
    which GitHub started actually issuing for this repository on or
    before 2026-08-19 -- confirmed live, the classic "owner/repo" format
    in github_repository above no longer matches what GitHub's OIDC
    token actually presents, and azure-backend-deploy.yml's first real
    run failed with AADSTS700213 until the federated credential's
    subject was corrected to this format. Get the real IDs from a
    failed azure/login run's own log line ("subject claim - ..."), or
    via `gh api repos/{owner}/{repo}` (id field) and
    `gh api orgs/{owner}` (id field). Left blank (default) falls back
    to the classic format in github_repository, for a repository GitHub
    hasn't migrated yet.
  EOT
  type        = string
  default     = ""
}

variable "github_deploy_branch" {
  description = "The single branch this environment's CI identity trusts. main for prod; a dedicated staging-deploy branch for staging -- never a wildcard."
  type        = string
  default     = "main"
}
