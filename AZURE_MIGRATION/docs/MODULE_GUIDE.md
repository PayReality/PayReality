# Module Guide

**Status:** final, Milestone 2. Each module's full detail (inputs, outputs, and — most importantly — what it deliberately does *not* do) lives in its own `README.md`, next to its code, so the documentation never drifts from the module it describes. This guide is the index, not a duplicate.

| Module | README | One-line purpose |
|---|---|---|
| `resource-group` | [`../terraform/modules/resource-group/README.md`](../terraform/modules/resource-group/README.md) | The container everything else lives inside |
| `networking` | [`../terraform/modules/networking/README.md`](../terraform/modules/networking/README.md) | VNet, three subnets, two generic Private DNS zones |
| `managed-identity` | [`../terraform/modules/managed-identity/README.md`](../terraform/modules/managed-identity/README.md) | Two identities: runtime, and CI/CD (GitHub OIDC federated) |
| `key-vault` | [`../terraform/modules/key-vault/README.md`](../terraform/modules/key-vault/README.md) | Owns every secret; real ones Terraform generates, placeholders for Render-originated ones |
| `postgres` | [`../terraform/modules/postgres/README.md`](../terraform/modules/postgres/README.md) | Flexible Server, private access, empty until Milestone 4 |
| `storage` | [`../terraform/modules/storage/README.md`](../terraform/modules/storage/README.md) | Blob Storage for uploads/evidence/receipts, empty until Milestone 7 |
| `container-registry` | [`../terraform/modules/container-registry/README.md`](../terraform/modules/container-registry/README.md) | Standard SKU, AAD-only, the gap Milestone 1 found and this project closes |
| `container-apps` | [`../terraform/modules/container-apps/README.md`](../terraform/modules/container-apps/README.md) | The compute target; same container, same embedded OPA, zero app-code change |
| `monitoring` | [`../terraform/modules/monitoring/README.md`](../terraform/modules/monitoring/README.md) | Log Analytics + App Insights, no alerts yet |
| `diagnostics` | [`../terraform/modules/diagnostics/README.md`](../terraform/modules/diagnostics/README.md) | One reusable module, called five times, routing every resource's telemetry into (9) |

## How to actually run this (once Milestone 3 is approved)

```
# One-time per subscription, local state, run from AZURE_MIGRATION/bootstrap/:
terraform init && terraform apply

# Then, from AZURE_MIGRATION/terraform/, per environment:
terraform init \
  -backend-config="resource_group_name=rg-payreality-tfstate" \
  -backend-config="storage_account_name=<bootstrap output>" \
  -backend-config="container_name=tfstate" \
  -backend-config="key=payreality-staging.tfstate"

terraform plan  -var-file=environments/staging.tfvars
terraform apply -var-file=environments/staging.tfvars
```

Repeat with `payreality-prod.tfstate` / `environments/prod.tfvars` for production — completely separate state, never shared.

## Root composition

`AZURE_MIGRATION/terraform/main.tf` is the only place these ten modules are wired together. `locals.tf` is the single source of every resource's name (`docs/NAMING_CONVENTION.md`); no module computes its own name.
