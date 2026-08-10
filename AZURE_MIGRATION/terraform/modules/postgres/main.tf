# Private access (VNet integration) via a delegated subnet -- Flexible
# Server's own networking mechanism, not a separate azurerm_private_
# endpoint resource on top of it. This is the one place in this project
# where "Private Endpoints where appropriate" is correctly answered "not
# here": Postgres Flexible Server doesn't use the generic Private
# Endpoint mechanism at all when running in VNet-integrated mode.

resource "random_password" "administrator" {
  length      = 32
  special     = true
  min_upper   = 1
  min_lower   = 1
  min_numeric = 1
  # Restricted to characters psycopg/libpq connection strings never need
  # to percent-encode, so the generated value can go straight into a
  # connection string without a second encoding step introducing its own
  # bug class.
  override_special = "-_"
}

# Flexible Server's private DNS zone: name is fixed by Azure to end in
# "postgres.database.azure.com" and is specific to this server, which is
# why it's created here rather than in modules/networking alongside the
# two generic, reusable privatelink zones.
resource "azurerm_private_dns_zone" "postgres" {
  name                = "${var.postgres_name}.private.postgres.database.azure.com"
  resource_group_name = var.resource_group_name
  tags                = merge(var.tags, { Purpose = "DNS resolution for the PayReality ${var.environment} Postgres Flexible Server" })
}

resource "azurerm_private_dns_zone_virtual_network_link" "postgres" {
  name                  = "link-${var.postgres_name}"
  resource_group_name   = var.resource_group_name
  private_dns_zone_name = azurerm_private_dns_zone.postgres.name
  virtual_network_id    = var.vnet_id
  registration_enabled  = false
}

resource "azurerm_postgresql_flexible_server" "this" {
  name                = var.postgres_name
  resource_group_name = var.resource_group_name
  location            = var.location

  version                = "16"
  administrator_login    = var.administrator_login
  administrator_password = random_password.administrator.result

  # Burstable is deliberate: this platform's own traffic today (confirmed
  # in AZURE_MIGRATION/MILESTONE_1_DISCOVERY.md) is pilot-scale. B1ms is
  # the smallest Burstable tier with enough memory for this application's
  # connection pool; sizing is a variable, not hardcoded, precisely so it
  # can change without a module edit once real load data exists.
  sku_name   = var.sku_name
  storage_mb = var.storage_mb

  backup_retention_days        = var.backup_retention_days
  geo_redundant_backup_enabled = var.geo_redundant_backup_enabled

  # Milestone 3 finding: the provider defaults this to true even when
  # delegated_subnet_id (below) already puts the server in private-access
  # (VNet Integration) mode, which has no public endpoint regardless --
  # explicit here so the plan output and the actual API request agree
  # with what modules/postgres/README.md and docs/NETWORKING_MODEL.md
  # already claim, rather than relying on an implicit default.
  public_network_access_enabled = false

  dynamic "high_availability" {
    for_each = var.high_availability_enabled ? [1] : []
    content {
      mode = "ZoneRedundant"
    }
  }

  delegated_subnet_id = var.postgres_subnet_id
  private_dns_zone_id = azurerm_private_dns_zone.postgres.id

  tags = merge(var.tags, { Purpose = "Primary application database for PayReality ${var.environment}" })

  depends_on = [azurerm_private_dns_zone_virtual_network_link.postgres]

  # Milestone 3 finding: `zone` is Optional but NOT Computed in provider
  # ~3.117 -- Azure auto-assigns an availability zone on create (this
  # server got "1"), but this config never asked for a specific zone, so
  # every later `terraform plan` reads that real value back and proposes
  # clearing it to null. The provider then refuses that specific change
  # outright ("`zone` can only be changed when exchanged with the zone
  # specified in `high_availability.0.standby_availability_zone`"),
  # failing the apply. Same class of issue, same fix, as
  # modules/container-apps' identical `infrastructure_resource_group_name`
  # finding: ignore it rather than let an unmanaged, provider-assigned
  # value fail every subsequent apply. See MILESTONE_3_DEPLOYMENT_REPORT.md.
  lifecycle {
    ignore_changes = [zone]
  }
}

resource "azurerm_postgresql_flexible_server_database" "app" {
  name      = var.database_name
  server_id = azurerm_postgresql_flexible_server.this.id
  collation = "en_US.utf8"
  charset   = "utf8"
}

# The generated administrator password's one and only durable home
# outside Terraform state (see docs/IDENTITY_MODEL.md's secret lifecycle
# section for why Terraform state itself is still sensitive and must be
# treated that way regardless of this).
resource "azurerm_key_vault_secret" "administrator_password" {
  name         = "postgres-administrator-password"
  value        = random_password.administrator.result
  key_vault_id = var.key_vault_id

  tags = merge(var.tags, { Purpose = "PostgreSQL Flexible Server administrator credential" })
}

resource "azurerm_key_vault_secret" "connection_string" {
  name = "database-url"
  # postgresql+psycopg:// -- the exact scheme app/config.py's DATABASE_URL
  # already expects (see MILESTONE_1_DISCOVERY.md); sslmode=require because
  # Flexible Server enforces TLS by default and the current Render
  # connection strings don't specify it (a compatibility gap named in
  # Milestone 1, closed here rather than left for Milestone 4 to discover).
  value        = "postgresql+psycopg://${var.administrator_login}:${random_password.administrator.result}@${azurerm_postgresql_flexible_server.this.fqdn}:5432/${var.database_name}?sslmode=require"
  key_vault_id = var.key_vault_id

  tags = merge(var.tags, { Purpose = "Full DATABASE_URL the application reads at startup" })
}
