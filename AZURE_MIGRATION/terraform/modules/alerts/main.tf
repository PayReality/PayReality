# Milestone 5: closes MILESTONE_4_RISK_REGISTER.md #1 (zero alert rules,
# nothing pages on failure). Five rules across the three resources most
# likely to silently fail: Postgres availability (the one Sev-0 here --
# a dead database is a full outage), Postgres storage (fills up slowly,
# actionable before it becomes an outage), Container App restarts (a
# crash loop reads as "restarting," not "down," to a casual health
# check), Container App CPU (approaching capacity), and Key Vault
# availability (every secret-backed startup depends on this working).
# Real metric names confirmed live via `az monitor metrics
# list-definitions` against each resource, not assumed from docs.

resource "azurerm_monitor_action_group" "critical" {
  name                = "ag-payreality-${var.environment}-critical"
  resource_group_name = var.resource_group_name
  short_name          = "pr-critical" # 12-char Azure limit

  email_receiver {
    name          = "primary-oncall"
    email_address = var.notification_email
  }

  tags = merge(var.tags, { Purpose = "Notification target for every alert rule in this module" })
}

resource "azurerm_monitor_metric_alert" "postgres_unavailable" {
  name                = "alert-${var.environment}-postgres-unavailable"
  resource_group_name = var.resource_group_name
  scopes              = [var.postgres_id]
  description         = "PostgreSQL Flexible Server is not responding to its own liveness check. Full outage for every feature that touches the database."
  severity            = 0
  frequency           = "PT1M"
  window_size         = "PT5M"

  criteria {
    metric_namespace = "Microsoft.DBforPostgreSQL/flexibleServers"
    metric_name      = "is_db_alive"
    aggregation      = "Average"
    operator         = "LessThan"
    threshold        = 1
  }

  action {
    action_group_id = azurerm_monitor_action_group.critical.id
  }

  tags = var.tags
}

resource "azurerm_monitor_metric_alert" "postgres_storage_high" {
  name                = "alert-${var.environment}-postgres-storage-high"
  resource_group_name = var.resource_group_name
  scopes              = [var.postgres_id]
  description         = "PostgreSQL storage is above 85%% -- actionable before it becomes an outage, not after."
  severity            = 2
  frequency           = "PT15M"
  window_size         = "PT15M"

  criteria {
    metric_namespace = "Microsoft.DBforPostgreSQL/flexibleServers"
    metric_name      = "storage_percent"
    aggregation      = "Average"
    operator         = "GreaterThan"
    threshold        = 85
  }

  action {
    action_group_id = azurerm_monitor_action_group.critical.id
  }

  tags = var.tags
}

resource "azurerm_monitor_metric_alert" "container_app_restarting" {
  name                = "alert-${var.environment}-container-app-restarting"
  resource_group_name = var.resource_group_name
  scopes              = [var.container_app_id]
  description         = "The Container App has restarted -- a crash loop reads as \"restarting,\" not \"down,\" to a simple health check, so this needs its own signal."
  severity            = 1
  frequency           = "PT5M"
  window_size         = "PT5M"

  criteria {
    metric_namespace = "Microsoft.App/containerApps"
    metric_name      = "RestartCount"
    aggregation      = "Total"
    operator         = "GreaterThan"
    threshold        = 0
  }

  action {
    action_group_id = azurerm_monitor_action_group.critical.id
  }

  tags = var.tags
}

resource "azurerm_monitor_metric_alert" "container_app_cpu_high" {
  name                = "alert-${var.environment}-container-app-cpu-high"
  resource_group_name = var.resource_group_name
  scopes              = [var.container_app_id]
  description         = "Container App CPU sustained above 80%% -- approaching the point where requests start queuing or failing."
  severity            = 2
  frequency           = "PT5M"
  window_size         = "PT5M"

  criteria {
    metric_namespace = "Microsoft.App/containerApps"
    metric_name      = "CpuPercentage"
    aggregation      = "Average"
    operator         = "GreaterThan"
    threshold        = 80
  }

  action {
    action_group_id = azurerm_monitor_action_group.critical.id
  }

  tags = var.tags
}

resource "azurerm_monitor_metric_alert" "key_vault_availability_low" {
  name                = "alert-${var.environment}-key-vault-availability-low"
  resource_group_name = var.resource_group_name
  scopes              = [var.key_vault_id]
  description         = "Key Vault request success rate below 95%% -- every secret-backed startup (DATABASE_URL, signing key, admin key) depends on this vault answering correctly."
  severity            = 1
  frequency           = "PT5M"
  window_size         = "PT5M"

  criteria {
    metric_namespace = "Microsoft.KeyVault/vaults"
    metric_name      = "Availability"
    aggregation      = "Average"
    operator         = "LessThan"
    threshold        = 95
  }

  action {
    action_group_id = azurerm_monitor_action_group.critical.id
  }

  tags = var.tags
}
