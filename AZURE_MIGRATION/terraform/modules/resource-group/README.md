# Module: resource-group

**Owner:** whoever holds the Azure subscription's Owner/Contributor role for this environment. **Purpose:** the single container every other module's resources live inside, and the unit Azure RBAC and cost reporting are scoped to.

## What this module creates

One `azurerm_resource_group`, named per `docs/NAMING_CONVENTION.md` (`rg-payreality-<environment>-<region>`), tagged with the project's common tags plus a `Purpose` tag.

## Inputs

| Name | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | Fully-computed name from the root module |
| `location` | string | yes | Azure region |
| `environment` | string | yes | `staging` or `prod` |
| `tags` | map(string) | yes | Common tags from the root module |

## Outputs

| Name | Description |
|---|---|
| `name` | Resource group name, consumed by every other module |
| `id` | Resource group resource ID |
| `location` | Echoed back so downstream modules don't need a separate `location` variable if they'd rather read it from here |

## Why this module is this small

One resource, deliberately. Splitting a single `azurerm_resource_group` into "a module" at all is only justified because every other module needs to depend on its output consistently, and because the root composition reads more clearly when every top-level concern -- including "the resource group exists" -- is a uniform module call, not a special case.
