# Bootstrap: creates only what Terraform needs to exist before the real
# infrastructure's remote state can live in Azure. This is a deliberate
# chicken-and-egg break, not an oversight: the root project's backend.tf
# points at a Storage Account for its state file, which means that
# Storage Account cannot itself be created by the same Terraform run
# that needs it as a backend.
#
# Run exactly once per subscription, with LOCAL state (this directory's
# own .tfstate, never committed -- see .gitignore). After this applies
# successfully, the root project's `terraform init` can use the Storage
# Account this creates as its backend, and this bootstrap config is not
# touched again unless the state storage itself needs to change.
#
# This satisfies "infrastructure must be reproducible from an empty Azure
# subscription" (Milestone 2, Absolute Rule 9) honestly: the reproduction
# path is "run bootstrap once, then run the root project," not a claim
# that a single `terraform apply` from nothing needs zero prerequisites --
# no Terraform-on-Azure setup can truthfully claim that for its own state
# storage.

terraform {
  required_version = ">= 1.7.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.117"
    }
  }
}

provider "azurerm" {
  features {}
}

variable "location" {
  description = "Azure region for the Terraform state storage account. Should match, or be close to, the region used for the real infrastructure, but is independent of it."
  type        = string
  default     = "eastus2"
}

resource "azurerm_resource_group" "state" {
  name     = "rg-payreality-tfstate"
  location = var.location

  tags = {
    Application = "PayReality"
    Purpose     = "Terraform remote state storage"
    ManagedBy   = "Terraform"
    CreatedBy   = "azure-migration-bootstrap"
  }
}

resource "random_string" "state_suffix" {
  length  = 6
  special = false
  upper   = false
  numeric = true
}

# Storage Account names are globally unique, lowercase alphanumeric only,
# 3-24 characters -- the random suffix exists only to satisfy global
# uniqueness, not as a naming convention choice (see
# ../docs/NAMING_CONVENTION.md for the real convention, which this
# bootstrap-only resource is deliberately exempt from since it exists
# once per subscription, never per-environment).
resource "azurerm_storage_account" "tfstate" {
  name                     = "sttfstatepr${random_string.state_suffix.result}"
  resource_group_name      = azurerm_resource_group.state.name
  location                 = azurerm_resource_group.state.location
  account_tier             = "Standard"
  account_replication_type = "GRS" # state loss is catastrophic and this is the cheapest resource in the whole project to make geo-redundant
  min_tls_version          = "TLS1_2"

  blob_properties {
    versioning_enabled = true # every historical state version recoverable, not just the latest

    delete_retention_policy {
      days = 30
    }
  }

  tags = {
    Application = "PayReality"
    Purpose     = "Terraform remote state storage"
    ManagedBy   = "Terraform"
    CreatedBy   = "azure-migration-bootstrap"
  }
}

resource "azurerm_storage_container" "tfstate" {
  name                  = "tfstate"
  storage_account_name  = azurerm_storage_account.tfstate.name
  container_access_type = "private"
}

output "resource_group_name" {
  value = azurerm_resource_group.state.name
}

output "storage_account_name" {
  value       = azurerm_storage_account.tfstate.name
  description = "Paste this into ../environments/*/backend.tf's storage_account_name."
}

output "container_name" {
  value = azurerm_storage_container.tfstate.name
}
