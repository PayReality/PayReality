# Azure Production Migration Program — Milestone 3: Deployment Report

**Status:** complete. Environment live in Azure `centralus`. Render remains production.

## Summary

Milestone 2's Terraform was deployed against a real Azure subscription for the first time. The first deployment attempt (`eastus2`) failed on a genuine, subscription-level regional capacity restriction and was abandoned; a second attempt (`centralus`) succeeded after five real, evidence-backed fixes were found and applied during the deployment itself. The staging environment is now fully live: 51 Terraform-managed resources, zero configuration drift, the real application container running (not a placeholder), Postgres migrated to the current schema, OPA running embedded exactly as designed, and the identity-first Key Vault/Storage security model the user approved mid-milestone fully implemented and verified.

## Why `eastus2` was abandoned

The first `terraform apply` (`rg-payreality-staging-eus2`) failed with four distinct root causes, each confirmed via direct `az` queries rather than assumed:

1. **PostgreSQL Flexible Server blocked by regional capacity restriction.** `az postgres flexible-server list-skus --location eastus2` returned `supportedServerVersions: []` with the message *"Subscriptions are restricted from provisioning in this region... open a support request."* Confirmed also restricted in `eastus`, `westus2`, `westeurope`; confirmed **not** restricted in `centralus`.
2. **`Microsoft.App` resource provider not registered** on this brand-new subscription — a one-time `409 MissingSubscriptionRegistration`, fixed via `az provider register --namespace Microsoft.App --wait`.
3. **Key Vault RBAC gap.** Being subscription Owner grants control-plane rights, not the data-plane role needed to create secrets on an RBAC-authorized vault — every secret write failed `403 ForbiddenByRbac`.
4. **Storage RBAC gap, compounded by a hard network block.** Same missing-role problem, plus `public_network_access_enabled = false` blocking Terraform (running outside the VNet, with no bastion/VPN) from the data plane entirely.

With the user's explicit, evidence-gated approval (verified no production traffic, no production data, and that the resource group was created solely by the failed apply), `rg-payreality-staging-eus2` was deleted (`az group delete --name rg-payreality-staging-eus2 --yes`) and confirmed fully gone (`az group exists` → `false`) before any rebuild began.

## Why `centralus` was selected

The only region, among the ones checked, with no subscription-level Postgres Flexible Server restriction. Selected as the new default in `variables.tf` (`location = "centralus"`, `location_short = "cus"`).

## The Key Vault naming incident

The first `centralus` apply also failed — a second, distinct problem, not a repeat of the `eastus2` causes:

```
Error: VaultAlreadyExists — "kv-pr-staging-adzg" ... a vault with the same name was recently
deleted but not purged after being placed in a recoverable state.
```

Root cause, confirmed via `az keyvault show-deleted`: Key Vault's `purge_protection_enabled = true` (deliberately set in Milestone 2 to protect the eventual Evidence signing key) means a deleted vault's name is **globally reserved and unpurgeable for the full soft-delete retention period** — 90 days here, expiring `2026-11-08` — even after its resource group is gone. The old name is also permanently bound to `eastus2`; recovering it would have undone the region migration.

**Fix, approved by the user:** rather than a one-off rename, Key Vault now draws its name from its own dedicated, higher-entropy `random_string.key_vault_suffix` (6 characters), decoupled from the 4-character suffix shared by Storage and Container Registry (both of which are freely reusable and were **not** touched by this fix). This is now the standing naming convention for every environment — see `docs/NAMING_CONVENTION.md`.

| | Old (permanently reserved until 2026-11-08) | New (active) |
|---|---|---|
| Key Vault name | `kv-pr-staging-adzg` | `kv-pr-staging-lu2swm` |
| Region | `eastus2` (soft-deleted) | `centralus` (live) |

No recovery or purge action was taken on the old vault, per the user's explicit instruction. It will age out of soft-delete on its own.

## Provider quirks found and fixed during deployment

All four are the same underlying class of issue — an attribute the AzureRM provider (`~> 3.117`) marks Optional but not Computed, so Azure's own auto-assigned value reads back as a diff on every subsequent plan. Each was confirmed live (via `az resource show` / `terraform plan`) before being fixed, and each fix is `ignore_changes` or an explicit pinned value, not a resource replacement:

| Resource | Attribute | Symptom | Fix |
|---|---|---|---|
| `azurerm_container_app_environment` | `infrastructure_resource_group_name` | Plan proposed replacing (destroying) the running environment | `lifecycle { ignore_changes }` |
| `azurerm_postgresql_flexible_server` | `zone` | Apply failed outright: *"`zone` can only be changed when exchanged with... `standby_availability_zone`"* | `lifecycle { ignore_changes }` |
| `azurerm_container_app` | `workload_profile_name` | Plan proposed an unwanted in-place update every run | `lifecycle { ignore_changes }` |
| `azurerm_monitor_diagnostic_setting` (storage) | target scope / metric categories | Apply failed: storage account's diagnostic API rejects `category_group = "allLogs"`; metric categories oscillated between `"AllMetrics"` and Azure's own translated `Capacity`/`Transaction` | Target the `blobServices/default` sub-resource, not the account; make `metric_categories` a per-target override in `modules/diagnostics` |

## Container image build and push

Built via `az acr build` (ACR Tasks — no local Docker daemon required), from `server/Dockerfile` unmodified (embedded OPA binary included, per the existing zero-cost pilot topology).

- **Registry:** `acrprstagingadzg.azurecr.io`
- **Repository:** `payreality-api`
- **Tags:** `staging-3f34349` (pinned to the exact source commit built), `staging-latest`
- **Digest:** `sha256:361fdd2d295e7891c79108c6da9d146744576f9987db99b4b2ef1af6f5f95f27`
- **Auth:** the Container App's managed identity holds `AcrPull` (granted in Milestone 2's `modules/container-registry`); the build/push itself used the signed-in operator's control-plane permissions via `az acr build`, not a stored credential.

A second real gap was found and fixed wiring this in: holding the `AcrPull` **role** is not sufficient on its own — Container Apps also needs an explicit `registry { server, identity }` block naming which identity to present when pulling from that specific server, or every revision fails to provision with `UNAUTHORIZED`. Invisible in Milestone 2 because the placeholder image (`mcr.microsoft.com/k8se/quickstart`) is public and needs no registry auth at all. Fixed in `modules/container-apps/main.tf`; the previously-running placeholder revision kept serving throughout (Container Apps' single-revision mode never dropped traffic during the fix).

## Final deployment state

- **Resource group:** `rg-payreality-staging-cus`, `centralus`
- **Terraform-managed resources:** 51 (see `MILESTONE_3_INFRASTRUCTURE_INVENTORY.md`)
- **`terraform plan`:** clean — *"No changes. Your infrastructure matches the configuration."*
- **Container App:** `Running`, real image, health and readiness probes passing
- **Git commit:** recorded in the commit accompanying this milestone, not duplicated here (see `MILESTONE_2_SUMMARY.md`'s same convention)

## What did not change

No file under `server/`, `SPECIFICATION/`, or `PRODUCT_ROADMAP/` was touched. Render remains production; no DNS change; no customer traffic; no database migration; no production cutover.
