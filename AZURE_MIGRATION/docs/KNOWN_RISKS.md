# Known Risks

**Status:** final, Milestone 2. Carries forward every unresolved risk from `AZURE_MIGRATION/MILESTONE_1_DISCOVERY.md` and adds what authoring the actual IaC surfaced.

## Carried forward from Milestone 1, still open

1. **Render's free-tier database expiry (2026-08-24) is unaffected by this milestone.** No Terraform in this project has been applied. Sprint 1's Task T1 remains the only thing that actually protects the safety net this whole program depends on, and it is independent of how fast this Azure work proceeds.
2. **Azure CLI's cached login requires interactive MFA.** Still true — this milestone authored IaC without ever calling `az` against a live subscription, exactly as instructed.
3. **Postgres SSL/connection-string compatibility.** Closed *in the IaC*, not yet verified live: `modules/postgres` writes a `DATABASE_URL` with `?sslmode=require` already appended. Milestone 3's verification step should confirm the application actually connects with this string against a real Flexible Server before considering this fully closed.
4. **Cost is estimated, not verified against live pricing** (`docs/COST_ASSUMPTIONS.md`) — validate before Milestone 3 applies anything.

## New, surfaced while authoring this milestone

5. **The `azurerm` provider version pinned (`~> 3.117`) uses `storage_account_name` on `azurerm_storage_container`, not `storage_account_id`.** A real, live bug caught only by actually running `terraform validate` — not a hypothetical: the first draft of `modules/storage` and `AZURE_MIGRATION/bootstrap` both used the wrong argument, since a newer provider major version (4.x) renamed it. Fixed in both places. Recorded here as evidence this milestone's verification step did real work, not a formality.
6. **Terraform state itself is sensitive** (it will contain the generated Postgres administrator password in plaintext, as Terraform state always does for any value it manages). Mitigated, not eliminated, by the bootstrap module's own choices: a GRS-replicated, versioned, soft-delete-protected storage account, access-controlled by whoever holds Azure RBAC on the `rg-payreality-tfstate` resource group. This is a standard, accepted Terraform limitation, not unique to this project — named explicitly so it's never mistaken for an oversight.
7. **The four Render-originated secrets are placeholders until Milestone 5.** If Milestone 3 or 6 is ever run out of order without Milestone 5 having happened first, the Container App will start with `ADMIN_API_KEY=PENDING-MILESTONE-5-MANUAL-ENTRY` and every operator-key-gated endpoint will simply reject every real request — a loud, immediate failure, not a silent security hole, but worth naming so it isn't mistaken for a bug when it's actually this design working as intended.
8. **`github_repository` defaults to `PayReality/PayReality` in both `environments/*.tfvars`.** This should be reconfirmed against the actual repository this program is running against before Milestone 3 applies — if it's ever wrong, the federated credential simply never matches and GitHub Actions authentication fails closed (not open), but it's still worth a human confirming this value once before it matters.
