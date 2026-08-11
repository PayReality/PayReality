# Milestone 5: closes the "no monitoring dashboard" success criterion.
# One Azure Portal Dashboard, six tiles -- a markdown title and five real
# metric charts against the resources this program has actually reasoned
# about (Container App, Postgres, Key Vault), using the same metric names
# already confirmed live via `az monitor metrics list-definitions` when
# modules/alerts was built, so this dashboard and those alert thresholds
# are looking at the same underlying data.

resource "azurerm_portal_dashboard" "this" {
  name                = "dash-payreality-${var.environment}"
  resource_group_name = var.resource_group_name
  location            = var.location
  dashboard_properties = templatefile("${path.module}/dashboard.json.tftpl", {
    environment        = var.environment
    container_app_id   = var.container_app_id
    container_app_name = var.container_app_name
    postgres_id        = var.postgres_id
    postgres_name      = var.postgres_name
    key_vault_id       = var.key_vault_id
    key_vault_name     = var.key_vault_name
  })

  tags = merge(var.tags, { Purpose = "At-a-glance operational view of Container App / Postgres / Key Vault for ${var.environment}" })
}
