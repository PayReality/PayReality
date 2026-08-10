# Module: diagnostics

**Owner:** platform/infrastructure engineer. **Purpose:** wires every other resource's own logs and metrics into the one Log Analytics workspace (`modules/monitoring`) — the "Diagnostic Settings" line item from Milestone 2's target architecture, kept as its own module rather than folded into `monitoring` because its job (route existing telemetry somewhere) is a genuinely different concern from `monitoring`'s (provide the somewhere).

## What this module creates

One `azurerm_monitor_diagnostic_setting` per entry in `var.targets` — called once from the root composition with every monitored resource's ID (Postgres, Key Vault, Storage Account, Container App Environment, Container Registry). `enabled_log { category_group = "allLogs" }` and `metric { category = "AllMetrics" }` for every target — the broadest, simplest setting available, chosen specifically because hand-maintaining a per-resource-type category list here would silently go stale the first time any one of five different Azure resource types changed its own supported categories upstream.

## Why one module, called five times, not five modules

Absolute Rule 6 ("everything must be modular") is best served here by genuine reuse: the five diagnostic settings this project needs are structurally identical (a resource ID in, a Log Analytics workspace ID in, a diagnostic setting out). Five near-identical modules would be five places to apply the same future change instead of one.

## Inputs / Outputs

`targets` (map of short key → resource ID) and `log_analytics_workspace_id` in; a map of the created diagnostic setting IDs out, keyed the same way `targets` was, so the root composition can reference any specific one if a future milestone ever needs to.
