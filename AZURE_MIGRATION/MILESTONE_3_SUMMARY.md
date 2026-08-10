# Azure Production Migration Program — Milestone 3: Summary

**Status:** complete. Stopping per the Completion Gate — awaiting approval before Milestone 4.

## Technical summary

Deployed Milestone 2's Terraform against a real Azure subscription for the first time. The first attempt (`eastus2`) failed on a genuine subscription-level Postgres regional capacity restriction and was abandoned after evidence-gated approval to delete it; a rebuild in `centralus` then hit a second real failure — a Key Vault naming collision caused by purge protection permanently reserving the old name — which was resolved by giving Key Vault its own collision-resistant naming convention, now standing project-wide. Along the way, an approved identity-first RBAC redesign replaced network isolation as Key Vault and Storage's primary security boundary (explicitly rejecting a jump host/bastion as the alternative), and four Terraform provider quirks were found and fixed. The environment now runs the real application container — not a placeholder — with OPA embedded and working exactly as designed, Postgres migrated to head schema, and zero configuration drift.

## Files changed

`AZURE_MIGRATION/terraform/variables.tf`, `locals.tf`, `main.tf`, `versions.tf`, `environments/{staging,prod}.tfvars`, `modules/key-vault/{main,outputs}.tf`, `modules/storage/{main,outputs}.tf`, `modules/postgres/main.tf`, `modules/container-apps/{main,variables}.tf`, `modules/diagnostics/{main,variables}.tf`, `docs/NAMING_CONVENTION.md`.

## Files created

This milestone's own 9 required documents, listed below.

## Infrastructure created

51 Terraform-managed Azure resources in `rg-payreality-staging-cus` (`centralus`) — full inventory in `MILESTONE_3_INFRASTRUCTURE_INVENTORY.md`. ~20 resources in `rg-payreality-staging-eus2` were created, then deleted, during the region-abandonment recovery.

## Tests executed

`terraform fmt -recursive -check`, `terraform validate`, six successive `terraform plan`/`apply` cycles (each re-validated before applying), five live security tests (unauthenticated Key Vault/Storage access, TLS/network posture checks), a live Log Analytics KQL query confirming real telemetry ingestion, direct `curl` checks against the running application's health endpoints, and the full application test suite (`pytest`, `server/`).

## Terraform validation results

Clean throughout. Final state: `terraform plan` → *"No changes. Your infrastructure matches the configuration."*

## Test results

`pytest`: **194 passed, 0 failed, 0 skipped** — identical to Milestone 2's count, confirming zero behavioral impact on the application.

## Risks discovered

Two new real failures, both resolved and documented in full in `MILESTONE_3_DEPLOYMENT_REPORT.md`: the `eastus2` regional capacity restriction, and the Key Vault soft-delete/purge-protection naming collision. Two known, intentionally-deferred gaps remain: the Evidence signing key is still a placeholder (Milestone 5's job), and Application Insights has no application-level telemetry yet (no APM SDK wired in) — both detailed in `MILESTONE_3_KNOWN_ISSUES.md`.

## Decisions made

Most consequential: Azure RBAC + Microsoft Entra ID as the primary security boundary for Key Vault and Storage management operations, in place of full network isolation, explicitly rejecting a jump host as the alternative; a dedicated, higher-entropy, decoupled random suffix for Key Vault naming specifically, now standing convention for every environment; `ignore_changes` as the correct fix for provider-quirk attributes, rather than fighting the provider's defaults every apply. Full reasoning for each in `MILESTONE_3_DEPLOYMENT_REPORT.md` and `MILESTONE_3_SECURITY_REVIEW.md`.

## Items requiring approval or attention before Milestone 4

1. Confirm `environments/prod.tfvars` should adopt the same Key Vault naming convention before any production apply is attempted — it will hit the same class of issue otherwise if a prod Key Vault is ever recreated.
2. Decide whether Application Insights instrumentation (an application-code change) is in scope for an upcoming milestone, or intentionally deferred further.
3. Milestone 5's real Evidence signing key remains the one placeholder blocking full functional (not platform) verification.
4. Sprint 1's Task T1 (Render database paid-tier upgrade) — still unresolved, still the risk the "Render stays production" principle depends on.

## Git commit

See the commit accompanying this milestone (hash recorded in the commit itself).

## Confirmation

Milestone 3 (Platform Deployment & Environment Foundation) is complete. Render remains the production environment — no DNS change, no customer traffic, no database migration, no production cutover occurred. Milestone 4 has **not** begun and will not begin without explicit approval, per the Completion Gate.
