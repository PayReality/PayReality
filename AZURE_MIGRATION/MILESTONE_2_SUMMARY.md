# Azure Production Migration Program — Milestone 2: Summary

**Status:** complete. Stopping per the Completion Gate — awaiting approval before Milestone 3.

## Technical summary

Authored a complete, modular Terraform IaC project for PayReality's Azure infrastructure: ten independent modules (`resource-group`, `networking`, `managed-identity`, `key-vault`, `postgres`, `storage`, `container-registry`, `container-apps`, `monitoring`, `diagnostics`), a root composition supporting two environments (`staging`, `prod`) from one shared module set, a one-time state-storage bootstrap configuration, a documented naming/tagging convention, and twelve supporting documents covering every topic this milestone's instructions named. Milestone 1's own discovery gap (a Container Registry with no compute service to run the image) is corrected here: Azure Container Apps is provisioned as the compute target. Zero Azure resource was created; zero application code was touched.

## Files changed

None — this is a from-scratch addition.

## Files created

63 files intended for commit under `AZURE_MIGRATION/` (`terraform/`, `bootstrap/`, `docs/`, plus this milestone's own reports). Full breakdown in `MILESTONE_2_MIGRATION_REPORT.md`.

## Infrastructure created

None. Design and authoring only, per the milestone's own instruction — no `terraform apply` was run.

## Tests executed

`terraform fmt -recursive -check` (both `terraform/` and `bootstrap/`), `terraform init -backend=false` + `terraform validate` (both directories), a manual check for unused variables (zero found across eleven `variables.tf` files), a manual check for duplicated resource declarations (zero found), and the full application test suite (`pytest`, `server/`).

## Terraform validation results

Both directories: formatting clean, `Success! The configuration is valid.` One real bug was found and fixed during this process (a provider-version-mismatched argument on `azurerm_storage_container`, present in both `bootstrap/main.tf` and `terraform/modules/storage/main.tf`) — full detail in the Verification and Migration Reports.

## Test results

`pytest`: **194 passed, 0 failed, 0 skipped** — identical to the count before this milestone began, confirming zero behavioral impact on the running application.

## Risks discovered

Carried forward from Milestone 1 (the Render database expiry, the MFA-blocked Azure CLI session, unverified live pricing) plus three new ones surfaced by actually authoring the IaC: the provider-version argument mismatch (found and fixed), Terraform state's inherent sensitivity (mitigated via the bootstrap module's GRS/versioned/soft-delete-protected storage account), and the placeholder-secret startup-failure mode if milestones are ever run out of order. Full detail in `docs/KNOWN_RISKS.md`.

## Decisions made

Ten, each with its reasoning stated in full in `MILESTONE_2_MIGRATION_REPORT.md` — among the most consequential: Container Apps over AKS/App Service, two separate managed identities rather than one shared identity, and placeholder Key Vault secrets with `ignore_changes` to resolve the tension between "the Container App needs a stable reference now" and "no secret value in a Terraform variable, ever."

## Items requiring approval before Milestone 3

1. Confirm the target Azure subscription and complete an interactive `az login` (MFA) — nothing in Milestone 3 can execute without this.
2. Confirm real Azure pricing against `docs/COST_ASSUMPTIONS.md`'s estimate.
3. Replace the `owner` and confirm the `github_repository` placeholder values in `environments/staging.tfvars` and `environments/prod.tfvars`.
4. Confirm the recommendation to resolve Sprint 1's Task T1 (Render database paid-tier upgrade) independently and in parallel — still unresolved, still the one risk this entire program's "Render stays online as the safety net" principle depends on.

## Git commit

See the commit accompanying this milestone (hash recorded in the commit itself, per this project's established practice of not duplicating a hash into a document that would immediately go stale on the next commit).

## Confirmation

Milestone 2 (Infrastructure as Code) is complete. Milestone 3 (Azure Foundation — actually applying this configuration) has **not** begun and will not begin without explicit approval, per the Completion Gate.
