# Milestone 3: Infrastructure Inventory

Live in `rg-payreality-staging-cus`, region `centralus`, subscription `09e09093-55bb-4fce-a487-5556fdf853d1`. 51 resources under Terraform management (`terraform state list`); table groups them by module for readability.

## Compute

| Resource | Name | Notes |
|---|---|---|
| Container Apps Environment | `cae-payreality-staging-cus` | VNet-integrated, Consumption workload profile |
| Container App | `ca-payreality-api-staging-cus` | Real image `acrprstagingadzg.azurecr.io/payreality-api:staging-3f34349`, 0.5 vCPU / 1Gi, `min_replicas=0` |
| Container Registry | `acrprstagingadzg` | Standard SKU |

## Data

| Resource | Name | Notes |
|---|---|---|
| PostgreSQL Flexible Server | `psql-payreality-staging-cus` | `B1MS`, 32 GiB, private access only (delegated subnet) |
| Postgres database | `payreality` | Empty, schema at head (`d7e28b4c91a6`) |
| Storage Account | `stprstagingadzg` | LRS, 3 private containers (`uploads`, `evidence-exports`, `authorization-receipts`) |
| Storage management policy | (default) | Tier-down rules; no delete action on any container |

## Security

| Resource | Name | Notes |
|---|---|---|
| Key Vault | `kv-pr-staging-lu2swm` | RBAC-only, purge protection on, 6 secrets |
| Managed Identity (app) | `id-payreality-containerapp-staging-cus` | `Key Vault Secrets User`, `Storage Blob Data Contributor`, `AcrPull` |
| Managed Identity (CI/CD) | `id-payreality-cicd-staging-cus` | `AcrPush`, GitHub Actions OIDC federated credential |
| Role assignment (×6) | see `MILESTONE_3_SECURITY_REVIEW.md` | Full least-privilege table there |

## Networking

| Resource | Name | Notes |
|---|---|---|
| VNet | `vnet-payreality-staging-cus` | 3 delegated subnets |
| Subnet | `snet-payreality-containerapps-staging-cus` | Container Apps Environment |
| Subnet | `snet-payreality-postgres-staging-cus` | Postgres delegated subnet |
| Subnet | `snet-payreality-privateendpoints-staging-cus` | Both Private Endpoints |
| Private Endpoint | `pe-kv-pr-staging-lu2swm` | Key Vault, `Approved` |
| Private Endpoint | `pe-stprstagingadzg-blob` | Blob Storage, `Approved` |
| Private DNS zone | `privatelink.vaultcore.azure.net` | Linked to VNet |
| Private DNS zone | `privatelink.blob.core.windows.net` | Linked to VNet |
| Private DNS zone | `psql-payreality-staging-cus.private.postgres.database.azure.com` | Linked to VNet |

## Observability

| Resource | Name | Notes |
|---|---|---|
| Log Analytics Workspace | `log-payreality-staging-cus` | Receiving container logs + 4 resources' diagnostic logs (confirmed via live KQL query) |
| Application Insights | `appi-payreality-staging-cus` | Provisioned; no app-level telemetry yet (see Known Issues) |
| Diagnostic Setting ×5 | `diag-postgres`, `diag-key-vault`, `diag-storage`, `diag-container-apps-env`, `diag-container-registry` | All `Succeeded` |

## Not Azure-billed (Terraform-internal)

`random_string.suffix`, `random_string.key_vault_suffix`, `random_password.administrator`, `time_sleep.wait_for_secrets_officer_rbac`, `time_sleep.wait_for_blob_contributor_rbac`, 2× `data.azurerm_client_config.current` — Terraform bookkeeping resources with no corresponding Azure bill line.

## Deleted, not recreated

`rg-payreality-staging-eus2` and everything in it (~20 resources from the failed `eastus2` attempt) — fully deleted, confirmed via `az group exists` → `false`. `kv-pr-staging-adzg` persists as a soft-deleted, unpurgeable artifact until `2026-11-08` (see Deployment Report) but is not a live, billed resource.
