# Naming Convention

**Status:** final, Milestone 2. **Single source of truth:** `AZURE_MIGRATION/terraform/locals.tf`. This document explains the convention; the code is the only place it's actually computed — no module invents its own name.

## Pattern

`<resource-type-abbreviation>-<app>-<qualifier>-<environment>-<region>` for every resource type with generous Azure naming limits (63–90 characters). Globally-unique, character-restricted resource types (Storage Account, Key Vault, Container Registry — lowercase alphanumeric only, no hyphens, ≤24 characters) use a shortened app code (`pr`) plus a 4-character random suffix instead, since a fixed convention alone cannot satisfy global uniqueness across every Azure customer.

## Abbreviations used

| Resource type | Abbreviation | Example (prod, East US 2) |
|---|---|---|
| Resource Group | `rg` | `rg-payreality-prod-eus2` |
| Virtual Network | `vnet` | `vnet-payreality-prod-eus2` |
| Subnet | `snet` | `snet-payreality-containerapps-prod-eus2` |
| Container Apps Environment | `cae` | `cae-payreality-prod-eus2` |
| Container App | `ca` | `ca-payreality-api-prod-eus2` |
| PostgreSQL Flexible Server | `psql` | `psql-payreality-prod-eus2` |
| User-Assigned Managed Identity | `id` | `id-payreality-containerapp-prod-eus2` |
| Log Analytics Workspace | `log` | `log-payreality-prod-eus2` |
| Application Insights | `appi` | `appi-payreality-prod-eus2` |
| Private Endpoint | `pe` | `pe-kv-pr-prod-a1b2` |
| Key Vault *(globally unique)* | `kv` | `kv-pr-prod-a1b2` |
| Storage Account *(globally unique, no hyphens)* | `st` | `stprproda1b2` |
| Container Registry *(globally unique, no hyphens)* | `acr` | `acrprproda1b2` |

## Environment values

Exactly two: `staging`, `prod` — matching Sprint 1's Infrastructure Blueprint decision that local/development stay on `docker-compose`, never a cloud environment. Enforced by a `terraform` variable validation block (`variables.tf`), not just this document's convention — an invalid environment value fails `terraform plan` immediately, not silently.

## Region

Configurable (`var.location`, default `eastus2`), with a matching short code (`var.location_short`, default `eus2`) that must be kept in sync by whoever changes the region — Azure's region-name-to-abbreviation mapping is a naming choice this project makes, not something Terraform derives automatically.

## Why one place computes every name

"One predictable naming strategy" (Milestone 2's own instruction) means exactly this: `locals.tf` is the only file with naming logic. Every module's `variables.tf` declares a plain `name` input; every module's `main.tf` just uses it. A name typo or convention drift can only happen in one file, ever.
