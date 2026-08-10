# One user-assigned Managed Identity, shared by the Container App for
# every Azure-service authentication it needs: pulling from Container
# Registry, reading secrets from Key Vault, and (Milestone 7) reading/
# writing Blob Storage. User-assigned rather than system-assigned
# deliberately: a system-assigned identity is deleted the moment the
# Container App is deleted, which would silently orphan every role
# assignment granted to it; a user-assigned identity's lifecycle is
# independent and its role assignments survive a Container App
# recreation (e.g. during a revision strategy change).
#
# This module creates the identity only. Role assignments granting it
# access to specific resources (AcrPull, Key Vault Secrets User, Storage
# Blob Data Contributor) live in the modules that own those resources
# (container-registry, key-vault, storage) -- each resource's own module
# is the one place that grants access to itself, consistent with "every
# resource must have a clear owner" (Absolute Rule 10): ownership of a
# permission grant belongs with the thing being accessed, not the thing
# accessing it.

resource "azurerm_user_assigned_identity" "container_app" {
  name                = var.identity_name
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = merge(var.tags, { Purpose = "Identity the PayReality API Container App authenticates to Azure services as" })
}

# A second, deliberately separate identity for CI/CD (image push, future
# deployment) -- least privilege, not convenience: the running
# application should never hold permissions to push a new container
# image or redeploy itself, and a CI pipeline should never hold Key
# Vault Secrets User or Storage Blob Data Contributor. Two identities
# with two clearly distinct purposes, per Absolute Rule 10, rather than
# one identity asked to be trusted for everything.
resource "azurerm_user_assigned_identity" "cicd" {
  name                = var.cicd_identity_name
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = merge(var.tags, { Purpose = "Identity GitHub Actions authenticates as to push images and (in a future milestone) deploy -- never granted application runtime permissions" })
}

# Workload identity federation: GitHub Actions authenticates to Azure
# using a short-lived OIDC token GitHub itself issues, federated to this
# identity -- no client secret or certificate to generate, store, rotate,
# or leak. This is the "infrastructure assumption" Milestone 2 asks CI/CD
# Preparation to establish; the GitHub Actions workflow file that actually
# uses it is not created in this milestone (see modules/container-registry's
# README for the exact deferred boundary).
resource "azurerm_federated_identity_credential" "github_actions" {
  count               = var.github_repository != "" ? 1 : 0
  name                = "github-actions-${var.environment}"
  resource_group_name = var.resource_group_name
  parent_id           = azurerm_user_assigned_identity.cicd.id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = "https://token.actions.githubusercontent.com"
  # Scoped to this environment's deploy branch only (e.g. main for prod,
  # a staging branch for staging) -- never "any branch, any workflow,"
  # which would let any contributor's feature-branch CI run push images
  # or deploy with this identity's permissions.
  subject = "repo:${var.github_repository}:ref:refs/heads/${var.github_deploy_branch}"
}
