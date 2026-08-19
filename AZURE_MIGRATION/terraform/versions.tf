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
    time = {
      source  = "hashicorp/time"
      version = "~> 0.12"
    }
  }

  # Partial backend configuration deliberately: the storage account name
  # is an output of ../bootstrap, not known until that has been applied
  # once per subscription (see ../bootstrap/main.tf's own comment). The
  # remaining keys, in particular `key` (payreality-staging.tfstate vs
  # payreality-prod.tfstate), are supplied per environment at
  # `terraform init` time -- this key is what actually isolates staging
  # and production state from each other, not two copies of this
  # configuration.
  #
  # ALWAYS run ./init-env.sh <prod|staging> to (re)initialize, never a
  # bare `terraform init`. A real incident (BACKLOG_V1_CLOSURE.md,
  # 2026-08-19): a bare init silently reuses whatever backend key is
  # cached locally from the last person's session, regardless of which
  # -var-file you're about to run plan/apply with -- planning staging's
  # tfvars against a stale prod-keyed cache produced a plan to destroy
  # and recreate 61 real production resources. init-env.sh's
  # -reconfigure flag makes every invocation an explicit, fresh
  # statement of which environment you mean, so this can't happen
  # silently again.
  backend "azurerm" {}
}

provider "azurerm" {
  features {}
}

provider "random" {}

provider "time" {}
