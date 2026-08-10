# One reusable module, called once per monitored resource from the root
# composition, rather than a separate near-identical diagnostics module
# per resource type -- "everything must be modular" (Absolute Rule 6)
# means one well-parameterized module reused five times, not five
# modules that would drift from each other the first time one of them
# needed a small change.
#
# `category_group = "allLogs"` rather than an explicit, hand-maintained
# list of log categories per resource type: Azure resource types add and
# rename diagnostic categories over time, and hardcoding today's list for
# five different resource types (Postgres, Key Vault, Storage, Container
# App, Container Registry) here would silently go stale the moment any
# one of them changes upstream -- "allLogs" tracks whatever the resource
# actually supports, automatically.

resource "azurerm_monitor_diagnostic_setting" "this" {
  for_each = var.targets

  name                       = "diag-${each.key}"
  target_resource_id         = each.value
  log_analytics_workspace_id = var.log_analytics_workspace_id

  enabled_log {
    category_group = "allLogs"
  }

  dynamic "metric" {
    for_each = lookup(var.metric_categories, each.key, ["AllMetrics"])
    content {
      category = metric.value
    }
  }
}
