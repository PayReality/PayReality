terraform {
  required_version = ">= 1.7.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.117"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Partial backend configuration deliberately: the storage account name
  # is an output of ../bootstrap, not known until that has been applied
  # once per subscription (see ../bootstrap/main.tf's own comment). The
  # remaining keys are supplied per environment at `terraform init` time:
  #
  #   terraform init \
  #     -backend-config="resource_group_name=rg-payreality-tfstate" \
  #     -backend-config="storage_account_name=<from bootstrap output>" \
  #     -backend-config="container_name=tfstate" \
  #     -backend-config="key=payreality-staging.tfstate"
  #
  # (key=payreality-prod.tfstate for the production environment -- this
  # is what actually isolates staging and production state from each
  # other, not two copies of this configuration.)
  backend "azurerm" {}
}

provider "azurerm" {
  features {}
}

provider "random" {}
