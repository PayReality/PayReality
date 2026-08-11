# Production Bootstrap Program — Phase 1: Revised Production Readiness Report

## The business clarification, and what it does and doesn't change

The user-supplied clarification — no production customers, organizations, principals, policies, or Evidence exist anywhere today; Render has only ever hosted the internal development/demo environment — is a business fact this program cannot independently verify (no tooling available to this session can inspect Render's database or determine what its contents "count as" from a business standpoint; that is inherently a business judgment, not a technical one). It is accepted as given, the same way any other stakeholder-supplied business fact would be.

What it changes: the entire premise of `PRODUCTION_CUTOVER/02_DATA_MIGRATION_ASSESSMENT.md` — that real data exists and must be moved. What it does not change: every *technical* finding from the prior audit that had nothing to do with data volume. Those are revalidated below against the actual repository, not assumed to still hold.

## Findings that still apply, unchanged

Re-verified live this session (`az group list`, DNS resolution, `az containerapp hostname list`, Terraform state list) — none of these depend on whether real customer data exists:

- **No Azure production environment exists.** Only `rg-payreality-staging-cus`. `environments/prod.tfvars` exists, is structurally complete, and has never been applied.
- **No production DNS record or SSL certificate exists** for the backend API. `payreality.aisecurewatch.com` resolves to Vercel (the frontend); no `api.*` record exists; the Container App has zero custom domains bound.
- **`CORS_ORIGIN` would be wrong** for real production traffic under the current environment-conditional logic, for the same reason as before — this is a labeling/environment question, not a data question.
- **`ANTHROPIC_API_KEY` remains a placeholder.** Independent of data migration entirely; still unresolved.

## Findings invalidated by the "no production data" clarification

- **"No data migration mechanism exists" is no longer a blocker.** It's still true that no such mechanism exists, but it's no longer a gap, because there is nothing to migrate. `PRODUCTION_CUTOVER/02_DATA_MIGRATION_ASSESSMENT.md` is superseded in its entirety by this program's Phase 2 (Production Bootstrap) instead.
- **The Evidence hash-chain continuity concern** (Milestone 6's finding that a new post-cutover record must correctly chain to a migrated pre-cutover one) **disappears.** There is no pre-existing chain to preserve — production's chain starts at record one, in Azure, for the first time.
- **The "register Render's signing key in Azure's registry" requirement disappears.** That was only needed to verify historical Evidence signed by Render's key. With no historical Evidence, Azure's own freshly-generated signing key (the same pattern already used and validated for staging in Milestone 5) is sufficient from day one.
- **The maintenance-window / read-only-freeze step in the old cutover plan disappears.** That existed to capture a final, consistent data snapshot before migrating it. With no data to snapshot, there is nothing to freeze.

## Findings that become simpler

- **Cutover plan**: collapses from an 11-step plan built around a migration boundary to a much shorter sequence: provision → bootstrap → verify → point DNS. See `07_DNS_CUTOVER_PLAN.md`.
- **Rollback plan**: the "database rollback" and "secrets rollback" sections in the prior plan existed mainly to reason about a migration gone wrong. With no migration, rollback is now almost entirely about the DNS/config reversion — see `08_ROLLBACK_PLAN.md`.
- **"Production Bootstrap" itself turns out to be substantially already-built**, not new work — see the next section and `02_PRODUCTION_BOOTSTRAP_SPECIFICATION.md`. This is this phase's single most consequential finding.

## Findings that disappear entirely

- Any question of data integrity validation (row counts, chain verification across a migration boundary, Alembic-head reconciliation between two live databases) disappears completely — there are no two databases to reconcile, only one being populated for the first time.
- The "Render read-only freeze" step and its own rollback (Milestone 6's Step 1) disappear — nothing is frozen because nothing is being extracted from Render.

## The one new finding this phase surfaced: bootstrap is mostly already code, not a program to build

Inspecting `server/app/main.py`'s `lifespan` startup sequence and the three services it calls (`organization_service.ensure_owner_bootstrapped`, `signing_key_service.ensure_current_key_registered`, `runtime_policy_service.reconcile_opa_with_active_policies`) shows all three are **already-shipped, idempotent, run-on-every-boot** logic — not something this program needs to design or build. This significantly narrows what "Production Bootstrap Specification" actually needs to cover: secrets and Terraform variables that feed these existing hooks, not new application code. Full detail in `02_PRODUCTION_BOOTSTRAP_SPECIFICATION.md`.

A related finding worth flagging explicitly, not silently acting on: `owner_email` (the email that becomes the real, bootstrapped production Organisation Owner) is wired in `main.tf` directly from `var.owner` — the same variable used purely for Azure resource-tag "accountability" labeling since Milestone 2. `prod.tfvars` currently sets this to `payreality.ceo@gmail.com`, inherited from the tagging convention, not from an explicit "who should be able to log in as the first production admin" decision. It may well be the right value — but it was never decided as that value specifically, and this program does not assume it is correct on its behalf. See `02_PRODUCTION_BOOTSTRAP_SPECIFICATION.md`.

## Summary of what remains before production bootstrap is possible

Unchanged from before: no Azure production environment, no DNS/certificate, `CORS_ORIGIN` needs correcting, `ANTHROPIC_API_KEY` needs a real value. New, simpler framing: no data migration needed at all; "bootstrap" is mostly confirming existing code behaves correctly against fresh secrets, not building new tooling. See `09_FINAL_GO_LIVE_RECOMMENDATION.md` for the verdict this phase's findings support.
