# Log Analytics + Application Insights only. No alert rule, no action
# group, no availability test is created here -- Milestone 2's own
# instructions are explicit: "Do not configure alerts yet. Only define
# architecture." Milestone 8 is where Sprint 1's already-designed alert
# categories (docs/../PRODUCT_ROADMAP/SPRINT_1/05_OBSERVABILITY_DESIGN.md)
# actually become azurerm_monitor_metric_alert / action_group resources.

resource "azurerm_log_analytics_workspace" "this" {
  name                = var.log_analytics_name
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = "PerGB2018"
  retention_in_days   = var.log_retention_days

  tags = merge(var.tags, { Purpose = "Central log/metric store for every PayReality ${var.environment} resource's diagnostic data" })
}

# Workspace-based Application Insights (the only mode Microsoft still
# recommends -- classic/standalone App Insights is deprecated), the
# direct Azure equivalent of the error-tracking/basic-APM tool Sprint 1's
# Observability Design already scoped (Task T6) -- this is that same
# capability, provisioned on Azure's own first-party service instead of
# a third-party SaaS, since the target platform is Azure now.
resource "azurerm_application_insights" "this" {
  name                = var.app_insights_name
  resource_group_name = var.resource_group_name
  location            = var.location
  workspace_id        = azurerm_log_analytics_workspace.this.id
  application_type    = "web"

  tags = merge(var.tags, { Purpose = "Request/dependency telemetry and error tracking for the PayReality API" })
}
