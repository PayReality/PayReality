# Module: key-vault

**Owner:** platform/infrastructure engineer (provisioning); whoever holds the `Key Vault Administrator` role thereafter (secret lifecycle). **Purpose:** the single owner of every PayReality secret value — see `docs/IDENTITY_MODEL.md` for the full secret lifecycle this vault anchors.

## What this module creates

- One Key Vault, RBAC-authorized (not the legacy access-policy model), purge protection on, 90-day soft-delete retention, **no public network access** — reachable only through its Private Endpoint.
- One Private Endpoint into the `private-endpoints` subnet, registered in the shared `privatelink.vaultcore.azure.net` DNS zone (from `modules/networking`).
- One role assignment: the Container App's managed identity gets **Key Vault Secrets User** — read-only, not `Key Vault Administrator` or `Key Vault Secrets Officer`. The application can read the secrets it needs at startup; it cannot create, rotate, or delete them. That stays a human or CI action, by design.

## What this module creates that is not yet a real secret

Four **placeholder** secrets (`evidence-signing-key-b64`, `evidence-signing-key-id`, `admin-api-key`, `anthropic-api-key`), each holding the literal string `PENDING-MILESTONE-5-MANUAL-ENTRY` and marked `lifecycle { ignore_changes = [value] }`. These exist now, with placeholder values, so `modules/container-apps` has a stable secret reference to wire up in this milestone — the *value* is Milestone 5's job, set directly with `az keyvault secret set` against these exact names, **never through a Terraform variable**. `ignore_changes` guarantees a later, unrelated `terraform apply` can never overwrite whatever real value Milestone 5 sets.

This is a different case from `modules/postgres`'s secrets, which *are* real values from the moment they're created — Terraform itself generates the database password, so Terraform managing that secret's value doesn't violate "secrets should never live inside Terraform variables" (nothing outside this Terraform run ever knew that value first). The four secrets here are the opposite case: they already exist in Render's production environment today, and moving that existing value through a `-var` just to reach Key Vault would be the exact anti-pattern this milestone's Identity instructions warn against.

## Inputs

| Name | Type | Required |
|---|---|---|
| `key_vault_name`, `resource_group_name`, `location`, `environment`, `tags` | — | yes |
| `private_endpoints_subnet_id`, `key_vault_private_dns_zone_id` | string | yes (from `modules/networking`) |
| `container_app_identity_principal_id` | string | yes (from `modules/managed-identity`) |

## Outputs

`id`, `name`, `uri` (consumed by `modules/container-apps` as an environment variable so the application's Azure SDK client knows which vault to read from).
