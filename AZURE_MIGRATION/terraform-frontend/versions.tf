# Milestone 16 (Vercel -> Azure Frontend Migration): a deliberately
# separate Terraform root from ../terraform, not a new module wired into
# it. The backend's root manages one "environment" (staging or prod) of
# tightly-coupled, VNet-integrated resources (Postgres, Container Apps,
# private endpoints) with its own staging/prod lifecycle. The two static
# frontends have no such coupling -- no VNet, no private networking, no
# database -- and their own natural lifecycle is per-application
# (marketing site, dashboard), not per-backend-environment. Entangling
# them into the same state file and module graph would make every
# frontend change plan against backend resources it has nothing to do
# with, exactly the complexity this milestone's own instructions warn
# against introducing.

terraform {
  required_version = ">= 1.7.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.117"
    }
  }

  # Same storage account as ../terraform (from ../bootstrap), a new blob
  # key so this state is fully independent of the backend's staging/prod
  # state files:
  #
  #   terraform init \
  #     -backend-config="resource_group_name=rg-payreality-tfstate" \
  #     -backend-config="storage_account_name=<from bootstrap output>" \
  #     -backend-config="container_name=tfstate" \
  #     -backend-config="key=payreality-frontend.tfstate"
  backend "azurerm" {}
}

provider "azurerm" {
  features {}
}
