# Production Bootstrap Program — Phase 3: Production Environment Gap Analysis

**Method note:** a live `terraform plan` against a real `payreality-prod.tfstate` backend key was attempted for this analysis and was **blocked by this environment's own permission controls** (switching Terraform's backend context is treated as a consequential action, even for `init`/`plan` with no `apply`). Per this program's engineering rules, this was not worked around — the analysis below is static, from direct inspection of the Terraform configuration and comparison against what actually exists for staging (`terraform state list` against the live staging backend, unaffected by the blocked command), not a live plan's output. This is disclosed so the analysis is understood as inspection-based, not execution-verified.

## What Terraform module set exists and would apply to prod

`environments/prod.tfvars` uses the identical root module composition as staging — the same ten-plus modules (`resource-group`, `networking`, `managed-identity`, `key-vault`, `postgres`, `storage`, `container-registry`, `monitoring`, `container-apps`, `alerts`, `dashboard`, `diagnostics`) that produced 51 real resources for staging. Nothing about the module set itself needs to change or be built — this is exactly the repeatability Milestone 2's own rules required ("two environments run from the identical module set with only `.tfvars` differing").

## What already exists for prod

**Nothing.** `az group list` (re-verified live this session) shows no resource group with `prod` in its name. `environments/prod.tfvars` is a file in the repository, not a deployed state.

## What still needs to exist, resource by resource

| Resource | Staging equivalent exists? | Prod-specific difference from staging |
|---|---|---|
| Resource Group | Yes (`rg-payreality-staging-cus`) | New group, `rg-payreality-prod-cus` (or whatever `location_short` resolves to) |
| VNet / subnets / private DNS zones | Yes | Same shape, new instance |
| Managed Identities (Container App, CI/CD) | Yes | New instances; CI/CD identity's federated credential branch changes to `main` (`main.tf`'s `github_deploy_branch = var.environment == "prod" ? "main" : "staging"` — already correct, no change needed) |
| Key Vault | Yes | New vault, own collision-resistant name (the Milestone 3 naming fix already applies to any new environment automatically, since it's in the shared module) |
| PostgreSQL Flexible Server | Yes | `postgres_geo_redundant_backup_enabled = true` for prod (already set in `prod.tfvars`) — a real, deliberate difference, not an oversight |
| Storage Account | Yes | `storage_replication_type = "GRS"` for prod (already set) |
| Container Registry | Yes | **New, separate registry** — `locals.tf` bakes `var.environment` into the ACR name, so prod does not and cannot share staging's registry; a real image build/push is required against this new registry (see `05_DEPLOYMENT_INITIALIZATION_PLAN.md`) |
| Container App / Environment | Yes | `container_apps_min_replicas = 1` for prod (already set — always-warm, no scale-to-zero, appropriate for production instead of staging's cost-saving scale-to-zero) |
| Log Analytics / App Insights | Yes | New instances |
| Alert rules + action group | Yes | New instances, `alert_notification_email` already set in `prod.tfvars` |
| Dashboard | Yes | New instance |
| Diagnostics | Yes | New instances |
| **Custom domain / DNS record** | **No — does not exist for staging either** | Not created by any Terraform module in this project at all; this is the one gap not solved by "apply the same modules again," and needs its own decision (see below) |
| **TLS certificate** | **No** | Blocked by the same gap — Azure Container Apps can issue a managed certificate automatically once a custom domain is bound, but nothing in this codebase does that binding today |

## The one genuine infrastructure gap: custom domain / certificate

This is the single item in this entire gap analysis that isn't "apply the existing modules a second time." Two options, neither built yet:

1. **Bind a real custom domain** (e.g. `api.payreality.aisecurewatch.com`) to the prod Container App and let Azure issue a managed certificate for it. Requires: a DNS record at the registrar pointing at the Container App's ingress, plus a `azurerm_container_app_custom_domain`-equivalent Terraform resource (not present in `modules/container-apps` today — a real, small Terraform addition, not a redesign).
2. **Point the frontend directly at the Container App's default `*.azurecontainerapps.io` hostname**, which already has a valid Microsoft-issued certificate for that exact hostname. No new Terraform resource needed; only a Vercel-side environment variable change at cutover time.

This program does not choose between these on its own authority — see `09_FINAL_GO_LIVE_RECOMMENDATION.md` for why this remains an open decision, not a default.

## `CORS_ORIGIN` — confirmed still needs correcting

`modules/container-apps/main.tf`: `CORS_ORIGIN = var.environment == "prod" ? "https://payreality.aisecurewatch.com" : "https://staging.payreality.aisecurewatch.com"`. Once `environment = "prod"` is the value actually applied (which it would be, applying `prod.tfvars` for the first time), **this resolves correctly to the real production frontend origin automatically** — this was only ever broken because the *staging* environment variable was being evaluated, not because the logic itself is wrong. **This gap disappears once a real prod environment is applied; no code change is needed.** This is a materially different conclusion than the prior audit's framing (which found CORS "wrong" in the context of possibly promoting staging to prod-in-place) — with a genuinely separate prod environment, the existing ternary already does the right thing.

## Conclusion

The infrastructure gap is narrower than the prior audit implied, now that "promote staging in place" is off the table in favor of "apply the existing prod.tfvars for real": almost everything is "the same Terraform, applied under prod naming," which this whole programme was explicitly built for since Milestone 2. The two real, new pieces of work are: (1) the custom domain/certificate decision and its small Terraform addition if Option 1 is chosen, and (2) building and pushing a real image to a new, prod-specific Container Registry.
