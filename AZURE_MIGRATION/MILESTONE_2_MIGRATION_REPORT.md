# Azure Production Migration Program — Milestone 2: Migration Report

**Status:** final. Every design decision this milestone made, and why — the record Absolute Rule 11 ("every decision must be documented") requires.

## Decisions made

1. **Azure Container Apps, not AKS or plain App Service, for compute.** Preserves the existing single-container, two-process (OPA + API) topology unchanged, with the least operational surface of the three real options — see `AZURE_MIGRATION/MILESTONE_1_DISCOVERY.md`'s target-architecture table for the full reasoning.
2. **Postgres Flexible Server's native VNet integration, not a generic Private Endpoint, for database networking.** These are two structurally different Azure mechanisms; Flexible Server's own is simpler and is what Microsoft's own guidance recommends for this exact case.
3. **Standard, not Premium, Container Registry SKU.** No current requirement for geo-replication, registry-level Private Endpoints, or retention policies — named as a real future-expansion path (`docs/FUTURE_EXPANSION.md`), not built ahead of need.
4. **Two managed identities, not one.** Least privilege: the running application and the CI/CD pipeline must never share a permission boundary. See `docs/IDENTITY_MODEL.md`.
5. **Workload identity federation (OIDC) for GitHub Actions, not a client secret.** Nothing long-lived to leak.
6. **Placeholder Key Vault secrets for the four Render-originated values, with `ignore_changes` on their value.** Resolves the real tension between "the Container App needs a stable secret reference now" and "secrets should never live inside Terraform variables" — the placeholder mechanism lets both be true simultaneously. See `docs/IDENTITY_MODEL.md`'s secret lifecycle section for the full reasoning, including why this is a genuinely different case from the Postgres password (which Terraform itself originates).
7. **A separate bootstrap Terraform configuration for remote state storage**, run once with local state. Addresses the chicken-and-egg problem of a Terraform backend that can't create itself, honestly rather than glossing over it.
8. **`revision_mode = "Single"` for Container Apps**, not multi-revision traffic splitting. No current deployment pattern needs it; adding it now would be unused abstraction.
9. **`category_group = "allLogs"` for every diagnostic setting**, not a hand-maintained per-resource-type category list. Avoids five different, independently-drifting lists of Azure log categories that change over time.
10. **No Azure DNS zone for the public domain.** Only Private DNS Zones (required for Private Endpoint resolution) are created — the public domain's DNS stays wherever it already is, consistent with Milestone 1's scope boundary (frontend/public-DNS was never named as in-scope).

## Files changed

Zero. This is a from-scratch addition — no pre-existing file was modified. See the Verification Report's Repository Safety section.

## Files created

71 files under `AZURE_MIGRATION/` (`terraform/`, `bootstrap/`, `docs/`), of which 63 are meant to be committed (the rest are the local `.terraform/` provider-plugin cache, excluded by the new `AZURE_MIGRATION/.gitignore` and never intended for version control). Full list in the Verification Report.

## Infrastructure created

**None.** This milestone is design and authoring only — no `terraform apply` was run against any real backend, no Azure resource of any kind exists as a result of this milestone.

## Errors found and fixed during this milestone

The pinned `azurerm` provider version (`~> 3.117`) does not support the `storage_account_id` argument on `azurerm_storage_container` — that argument was introduced in a later provider major version (4.x). The first draft of both `terraform/modules/storage/main.tf` and `bootstrap/main.tf` used it; `terraform validate` caught both immediately. Fixed by using `storage_account_name` (the correct argument for the pinned version) in both places, followed by a full re-`fmt`/re-`validate` pass confirming the fix and finding nothing else. This is exactly the kind of error real verification is supposed to catch — recorded here, not smoothed over, because Absolute Rule 4 ("no shortcuts") includes not pretending a first draft was correct when it wasn't.

## Application code changes

None, and none required. Every Key-Vault-backed secret and plain environment variable this Container App configuration sets matches `server/app/config.py`'s existing `Settings` fields exactly (confirmed directly against `AZURE_MIGRATION/MILESTONE_1_DISCOVERY.md`'s inventory) — Milestone 6 will need to build and push a real image, but nothing about *this* milestone's design requires a single line of `server/app/` to change.

## Migration dependencies this milestone's authoring surfaced (beyond Milestone 1's)

See `docs/MIGRATION_DEPENDENCIES.md` in full — summarized: `bootstrap/` must be applied before the root project's remote backend can be configured; `owner` and `github_repository` placeholders in both `.tfvars` files need real values before the first real apply; real Azure pricing should be checked against `docs/COST_ASSUMPTIONS.md`'s estimate before Milestone 3.
