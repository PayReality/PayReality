# Networking Model

**Status:** final, Milestone 2. **Principle:** tighten this project's existing security instincts (OPA bound to loopback, unreachable from outside its container — already true today, per `AZURE_MIGRATION/MILESTONE_1_DISCOVERY.md`), don't invent new ones it doesn't need.

## VNet and subnets

One VNet (`10.20.0.0/16` by default — chosen outside the common `10.0.0.0/16`/`10.1.0.0/16` defaults specifically to reduce collision risk if this network is ever peered with another), three subnets:

| Subnet | CIDR | Delegation | Holds |
|---|---|---|---|
| `container-apps` | `/23` | `Microsoft.App/environments` | The Container Apps Environment |
| `postgres` | `/24` | `Microsoft.DBforPostgreSQL/flexibleServers` | Postgres Flexible Server (VNet-integrated, no separate Private Endpoint) |
| `private-endpoints` | `/24` | none | Private Endpoint NICs for Key Vault and Storage |

The `container-apps` subnet is deliberately sized larger (`/23`, 510 usable addresses) than the `/27` minimum Azure allows for a consumption-only environment, so a future move to Container Apps workload profiles doesn't require re-addressing the network — the one piece of intentional headroom in this design, not over-engineering, since it costs nothing to reserve address space that would otherwise sit unused anyway.

## Private endpoints

Key Vault and Blob Storage each get a real `azurerm_private_endpoint`, registered in a shared, generic Private DNS zone (`privatelink.vaultcore.azure.net`, `privatelink.blob.core.windows.net`) linked to the VNet. **Postgres does not use this mechanism** — Flexible Server's own VNet-integration (a delegated subnet plus its own dedicated Private DNS zone, created in `modules/postgres` because its name is tied to the server itself) is a structurally different, Postgres-specific private-access model. Neither Key Vault nor Storage nor Postgres has any public network path; `public_network_access_enabled = false` (or Postgres's equivalent delegated-subnet-only access) is set explicitly on every one of them, not left to a platform default.

## Outbound internet strategy

Container Apps' consumption-plan environment provides its own managed outbound NAT by default — no static egress IP today. Named, not built: a NAT Gateway for a fixed outbound IP is a real, understood option (`docs/FUTURE_EXPANSION.md`) if a third-party integration (e.g. a bank's IP-allowlisted API) ever requires one. Provisioning it now, with no current integration that needs it, would be over-engineering.

## Ingress strategy

External HTTPS-only ingress on the Container App, Azure's own managed TLS certificate on the default `*.azurecontainerapps.io` domain. No custom domain is bound in this milestone — that's explicitly Milestone 9's step, gated on this whole program's own verification checkpoints, not something to pre-wire now just because it would be convenient later.

## Future expansion

- NAT Gateway for static outbound IP, if a specific integration needs it.
- Azure Front Door or Application Gateway, if a WAF requirement or multi-region routing need ever materializes — neither is justified by anything found in this program's own risk analysis so far.
- A Network Security Group with explicit rules, if a future resource in this VNet doesn't already have its access boundary enforced by delegation/Private-Endpoint the way everything in this design does today.

## What this model deliberately does not include

An NSG with hand-written rules (nothing in this design needs one on top of delegation + Private Endpoints — see `modules/networking/README.md`), a hub-and-spoke topology (this is one application, one environment pair — a single VNet is the honest match for that scale), and any public route to Postgres, Key Vault, or Storage, under any circumstance.
