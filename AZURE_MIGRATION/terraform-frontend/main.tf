# Milestone 16: two independent Azure Static Web Apps, one per frontend
# application. Each gets its own free `*.azurestaticapps.net` hostname
# immediately -- this IS the "staging" environment Phase 3 asks for
# (build/deploy/validate against it with no DNS change), not a separate
# resource. The custom domain (aisecurewatch.com/www, or
# payreality.aisecurewatch.com) is a SEPARATE resource
# (azurerm_static_web_app_custom_domain), added only once staging
# validation has passed -- see custom-domains.tf, deliberately not
# defined here, so `terraform apply` for this file alone can never touch
# DNS-adjacent state.
#
# Deployment mechanism: GitHub Actions using each app's own
# `azure_static_web_apps_api_key` (the deployment token SWA issues per
# resource), not Terraform's own CI/CD -- matches this project's existing
# split (Terraform provisions infrastructure; GitHub Actions/az CLI
# handle application deployment) rather than inventing a new pattern.

resource "azurerm_static_web_app" "website" {
  name                = "stapp-payreality-website-prod-${var.location_short}"
  resource_group_name = var.resource_group_name
  location            = var.location
  sku_tier            = var.sku_tier
  sku_size            = var.sku_tier

  tags = merge(var.tags, {
    Repository = var.github_repository_website
    App        = "marketing-website"
  })
}

resource "azurerm_static_web_app" "dashboard" {
  name                = "stapp-payreality-dashboard-prod-${var.location_short}"
  resource_group_name = var.resource_group_name
  location            = var.location
  sku_tier            = var.sku_tier
  sku_size            = var.sku_tier

  tags = merge(var.tags, {
    Repository = var.github_repository_dashboard
    App        = "dashboard"
  })
}
