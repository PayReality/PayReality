# Module: networking

**Owner:** platform/infrastructure engineer. **Purpose:** the network boundary every other resource either lives inside (Container Apps, Postgres) or is reachable only through (Key Vault, Storage via Private Endpoint).

## What this module creates

- One Virtual Network.
- Three subnets: `container-apps` (delegated to `Microsoft.App/environments`), `postgres` (delegated to `Microsoft.DBforPostgreSQL/flexibleServers`), `private-endpoints` (undelegated).
- Two generic Private DNS Zones (`privatelink.vaultcore.azure.net`, `privatelink.blob.core.windows.net`) and their VNet links, so Key Vault's and Storage's Private Endpoints (created in their own modules) resolve correctly from inside this VNet.

## What this module deliberately does not create

- Postgres's own Private DNS Zone. Its name is tied to the Postgres server resource itself (Flexible Server's VNet-integration mechanism), so it's created in `modules/postgres`, which already needs to know the server's name -- creating it here would mean passing the server name backward into this module, an awkward and unnecessary coupling.
- A Network Security Group. Not because one is never useful, but because Container Apps Environment and Postgres Flexible Server's delegated-subnet model already enforce the access boundaries this project actually needs (see `docs/NETWORKING_MODEL.md`); adding NSG rules on top with nothing left for them to restrict would be exactly the over-engineering this milestone's instructions warn against.
- A NAT Gateway for static outbound IP. Named as a real future-expansion item (`docs/FUTURE_EXPANSION.md`) for if a third-party integration ever requires IP allowlisting -- not built speculatively now.

## Inputs

| Name | Type | Required | Description |
|---|---|---|---|
| `resource_group_name`, `location`, `environment`, `tags` | — | yes | Standard cross-module inputs |
| `vnet_name` | string | yes | Fully-computed name from root |
| `vnet_address_space` | list(string) | no | Default `["10.20.0.0/16"]` |
| `subnet_container_apps_name` / `_cidr` | string | name yes, cidr no | Default `/23` |
| `subnet_postgres_name` / `_cidr` | string | name yes, cidr no | Default `/24` |
| `subnet_private_endpoints_name` / `_cidr` | string | name yes, cidr no | Default `/24` |

## Outputs

`vnet_id`, `vnet_name`, `container_apps_subnet_id`, `postgres_subnet_id`, `private_endpoints_subnet_id`, `key_vault_private_dns_zone_id`/`_name`, `blob_storage_private_dns_zone_id`/`_name` — consumed by `modules/container-apps`, `modules/postgres`, `modules/key-vault`, and `modules/storage` respectively.
