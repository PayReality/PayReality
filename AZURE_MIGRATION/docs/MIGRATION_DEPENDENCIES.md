# Migration Dependencies

**Status:** final, Milestone 2. Restates and refines `AZURE_MIGRATION/MILESTONE_1_DISCOVERY.md`'s dependency section now that the actual module graph exists to check it against.

## What must happen before Milestone 3 can apply anything

1. A human runs `az login` interactively (MFA) — confirmed still required as of this milestone (`docs/KNOWN_RISKS.md` #2).
2. `AZURE_MIGRATION/bootstrap/` is applied once (local state) to create the Terraform remote-state storage account.
3. Real Azure pricing is checked against `docs/COST_ASSUMPTIONS.md`'s estimate.
4. `environments/staging.tfvars` and `environments/prod.tfvars`'s `owner` placeholder is replaced with a real accountable identifier.
5. `github_repository` in both `.tfvars` files is reconfirmed against the actual repository.

## Module apply order (Terraform resolves this automatically from references — stated here for human readability)

`resource-group` → `networking` → `managed-identity` → (`key-vault`, `postgres`, `storage`, `container-registry`, `monitoring` — these five have no dependency on each other, only on the first three) → `container-apps` (depends on all of the above) → `diagnostics` (depends on every resource it monitors already existing).

## What later milestones depend on from this one

| Later milestone | Depends on |
|---|---|
| 3 (Azure Foundation) | This entire Terraform project, plus the human prerequisites above |
| 4 (Database Migration) | `modules/postgres`'s empty server + database existing |
| 5 (Secrets) | `modules/key-vault`'s four placeholder secrets existing with stable names |
| 6 (Backend Deployment) | `modules/container-registry` (a place to push to) and `modules/container-apps` (a place to deploy to) both existing |
| 7 (Storage Migration) | `modules/storage`'s three empty containers existing |
| 8 (Monitoring) | `modules/monitoring` + `modules/diagnostics` existing, ready for alert rules to be added on top |
| 9 (Production Cutover) | Every prior milestone verified — this document does not itself grant that verification |
