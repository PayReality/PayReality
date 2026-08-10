# Module: monitoring

**Owner:** platform/infrastructure engineer. **Purpose:** the observability foundation every other module's diagnostic data (`modules/diagnostics`) and Milestone 8's alert rules both build on.

## What this module creates

One Log Analytics Workspace (`PerGB2018`, 30-day retention by default) and one workspace-based Application Insights instance (`application_type = "web"`) — the modern, Microsoft-recommended mode; classic/standalone App Insights is deprecated.

## What this module deliberately does not create

**No alert rule. No action group. No availability test.** Milestone 2's own instructions are explicit: "Do not configure alerts yet. Only define architecture." Alert *categories* (P1/P2/informational) are already fully designed in Sprint 1's `PRODUCT_ROADMAP/SPRINT_1/05_OBSERVABILITY_DESIGN.md` — Milestone 8 is where those become real `azurerm_monitor_metric_alert`/`azurerm_monitor_action_group` resources against the workspace and App Insights instance this module provisions now.

## Relationship to Sprint 1's Task T6

This module *is* Task T6 (error tracking / basic APM), re-scoped onto Azure's own first-party service now that Azure is the target platform, rather than the third-party SaaS (Sentry) Sprint 1 originally recommended when Render was still the only platform in scope. Same capability, same justification (one lightweight tool, not a heavier stack), different vendor because the vendor question changed underneath it — not a reversal of that decision's reasoning.

## Inputs / Outputs

See `variables.tf`/`outputs.tf`. `app_insights_connection_string` is Application Insights' own connection string — Azure does not treat this as a secret (it's designed for client-side embedding), but it is still environment-specific and therefore a module output, not a hardcoded value anywhere.
