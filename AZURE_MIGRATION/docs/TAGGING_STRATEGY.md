# Tagging Strategy

**Status:** final, Milestone 2. **Single source of truth:** `locals.common_tags` in `AZURE_MIGRATION/terraform/locals.tf`, merged onto every resource this project creates via `merge(var.tags, { Purpose = "..." })`.

## The common tags, and where each value comes from

| Tag | Source | Example |
|---|---|---|
| `Environment` | `var.environment` | `prod` |
| `Application` | Fixed literal | `PayReality` |
| `Owner` | `var.owner` (required — no default) | set per environment in `environments/*.tfvars` |
| `CostCenter` | `var.cost_center` (default `engineering`) | a single-value default is deliberate at this company's current size; override only if a real second cost center exists |
| `ManagedBy` | Fixed literal | `Terraform` — true today, and a signal that hand-editing this resource in the Portal will be overwritten on the next `apply` |
| `Version` | Fixed literal (this milestone's name) | `milestone-2` |
| `CreatedBy` | Fixed literal | `azure-migration-program` |

## The per-resource `Purpose` tag

Every module adds exactly one additional tag, `Purpose`, describing in a short sentence what that specific resource is for — visible directly in the Azure Portal's tag list without needing to cross-reference this documentation. This is the one tag every module's own code determines, not `locals.tf`, because only the module creating a resource knows precisely why that resource exists.

## Why every resource inherits these, with no exceptions

Every module accepts `tags` as a required input and passes it straight to `merge()` — there is no code path in this project that creates a resource without the common tags. Cost reporting, ownership lookup, and "what is this thing" all answer the same way regardless of which of the ten modules created the resource.
