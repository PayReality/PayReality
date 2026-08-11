# Module: dashboard

**Owner:** platform/infrastructure engineer. **Purpose:** closes Milestone 5's "monitoring dashboards completed" success criterion — a single Azure Portal Dashboard giving an at-a-glance operational view without needing to open three separate resource blades.

## What this module creates

One `azurerm_portal_dashboard` with six tiles: a markdown title, then five metric charts covering Container App (CPU/Memory, Requests/Restarts), PostgreSQL (CPU/Storage, Connections/Availability), and Key Vault (Availability/API hits) — the same three resources `modules/alerts` watches, using the same metric names, so the dashboard and the alert thresholds are reading the same underlying data.

## Why a Portal Dashboard, not a Workbook

Both are valid Azure-native choices. A Dashboard was chosen for this milestone because it's the simpler of the two to keep in Terraform as a single resource with a plain JSON body (`dashboard.json.tftpl`), and because "at-a-glance" is exactly a Dashboard's purpose — a Workbook's strength (parameterized, multi-step analysis) isn't what this gap needed closed.

## Inputs / Outputs

Every resource ID and display name for the three watched resources, plus the usual `resource_group_name`/`location`/`environment`/`tags`. Outputs the dashboard's resource ID and a direct Azure Portal URL.
