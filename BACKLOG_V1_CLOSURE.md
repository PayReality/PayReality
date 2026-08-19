# PayReality: v1 Backlog Closure Plan

**Status:** current as of 2026-08-19, produced by re-verifying every claim directly against live code and tests today, not carried forward from older documents.

**Supersedes:** `PAYREALITY_ARCHITECTURE_REVIEW_AND_ROADMAP.md`, `PAYREALITY_ENTERPRISE_HARDENING_PLAN.md`, and `PAYREALITY_ENTERPRISE_V1_MASTER_ROADMAP.md` (all untracked, never committed). Those three were snapshots from right after Authority Intelligence Phase 5 (commit `22bb3b8`), before Milestones 2 through 16 closed most of what they flagged. Kept in the working tree for historical reference only, but do not treat their open items as current without re-checking; most no longer are.

**Method:** every item below was verified today by reading the actual current code, tests, or config, not inferred from memory or an older doc. Where something genuinely could not be checked from a repo (live infra state, an external CRM), it's marked **Unverified** rather than assumed either way.

---

## P0: Resolved 2026-08-19

**Render fully retired.** DNS had already been on Azure exclusively since Milestone 7 (`api.aisecurewatch.com` verified resolving only to `ca-payreality-api-prod-cus`, Render's own `onrender.com` URL confirmed reachable only directly, never via any real client). Before deletion: queried both databases directly and found they had genuinely diverged, not a superset relationship (Render's single original organization had 9 decisions/evidence/policy records with no equivalent in Azure, versus Azure's 6 orgs/24 users from post-cutover RBAC testing). Took a full CSV export of all 41 tables from Render's Postgres, verified row counts matched exactly, saved to a local, uncommitted backup (`C:\Users\user\Downloads\render-db-backup-2026-08-19\`, contains signing-key material, keep it local and never commit or upload it). Then deleted the Render web service (`srv-d9idj8t8nd3s739o5dsg`) and Postgres instance (`payreality-db`) via the Render API; confirmed both gone (empty service/postgres lists, `onrender.com` URL now 404) and production unaffected (`api.aisecurewatch.com` still healthy throughout). `render.yaml` marked historical in place, not deleted.

**Deliberately not done:** migrating Render's one diverged organization's history into Azure as live data. Decision made explicitly: the cold backup is enough, that data doesn't need to be queryable in the live system.

---

## P1: Resolved 2026-08-19

All six items closed in one pass, each verified against real code/tests/live API before and after:

- **Homepage/Assurance legacy table** -- `PlatformOverview.tsx`/`LiveAssurance.tsx` now read the real lifecycle dashboard's `counts_by_state`, matching the current multi-policy model instead of the old single-active-policy one.
- **Website SDK code samples** -- fixed `authorize()` in `Sdks.tsx`/`GettingStarted.tsx` to match the real signature (`principal`, `operation`, `resource`, `resource_data`), verified by binding the exact call against `agent.py`'s real signature. `IntegrationExamples.tsx`/`IntegrationGuides.tsx` only mention `authorize()` in prose, no code block to fix.
- **"Sub-millisecond" claim** -- ran a real benchmark against a compiled bundle and a live local OPA server rather than guessing: full decision round trip measured 1.4-2.5ms typical (pure Rego evaluation alone is sub-millisecond at the median, but that's not what most of the copy was describing). Removed the claim from all 7 files, kept the real differentiator (deterministic, evaluated before execution).
- **Authority Graph messaging** -- corrected across `AuthorityGraph.tsx`, `RuntimeAuthority.tsx`, and `Platform.tsx`: the graph is a reviewed discovery artifact, not something queried live; what's actually evaluated at decision time is the compiled Runtime Policy bundle a team publishes from that review.
- **Evidence rotation/chain UI** -- built both views against the real backend endpoints. Verified response shapes directly against the live production API and backend test assertions before building, which caught a field (`active: bool`) missed on first read of the schema.
- **Field-vocabulary validation** -- Compiler V2 now validates condition field names, not just actions. A condition against a nonexistent field (real example found: `vendor.approved`, never actually in the OPA intent dict) is now a compile-time `INVALID_FIELD` error instead of silently never matching.

---

## P2: Three of four resolved 2026-08-19

**Runtime Policy Lifecycle live-database status: RESOLVED, live-verified.** Confirmed the unit tests are genuinely fake-session-only (self-disclosed in `test_runtime_policy_lifecycle_service.py`'s own docstring). Ran a real, full lifecycle exercise against staging's actual Postgres + OPA: create, submit-for-review, approve, activate, edit (version bump), submit, approve, re-activate, rollback, re-submit, re-approve, re-activate, schedule a retirement, cancel that schedule, and retire. Every transition succeeded exactly as designed; the timeline endpoint returned all 19 real, persisted events in order. One genuine behavioral finding surfaced along the way: rollback doesn't reactivate the old version directly, it creates a new draft version with the old content (`rollback_of_version` set), which then needs its own submit/approve/activate cycle -- an audit-preserving design choice, not a bug, but worth knowing.

**A real, valuable side-finding: staging was running a badly stale image** (`staging-15b2114`, the very first Azure AI Foundry commit, predating Milestone 2's entire multi-tenant/organization-lifecycle system) -- confirmed by a 404 on `POST /v1/organizations`, a route that plainly didn't exist in that build. Rebuilt and deployed a current image (`staging-602de59`) via `az acr build` + `az containerapp update` before the lifecycle exercise could even run; new revision confirmed healthy at 100% traffic. Updated `staging.tfvars`'s `container_image` to match, so this doesn't silently drift back on a future `terraform apply`.

**Terraform state separation: RESOLVED.** The near-miss (see below) turned out to be an operator-safety gap, not a design flaw: the partial backend config already separates state correctly by key (`payreality-prod.tfstate` vs `payreality-staging.tfstate`), but a bare `terraform init` silently reuses whatever key is cached locally from the last session, with no warning. Added `init-env.sh <prod|staging>`, which always passes `-reconfigure` with an explicit key, so every init is a fresh, unambiguous statement of intent. Verified against both environments afterward: `terraform plan` now shows real, expected results, "No changes" for staging and a single one-field `container_image` drift for prod (harmless, caused by the CD pipeline now owning that field directly), not 61 resources about to be destroyed. Documented in `versions.tf` and a new `AZURE_MIGRATION/terraform/README.md`.

**The near-miss that surfaced this, recorded plainly for the record:** running `terraform plan -var-file=environments/staging.tfvars` in this state directory produced a plan to destroy and recreate 61 real resources, because the local Terraform state in scope was prod's, not staging's -- the plan would have converted prod's resource group/storage account/Postgres into staging's names had it ever been applied. **Nothing was applied; `plan` is read-only,** and the gap is now closed per above.

**No backend CD pipeline: RESOLVED, live-verified twice.** Added `.github/workflows/azure-backend-deploy.yml`: tests gate build gate deploy gate a real health check against `api.aisecurewatch.com`. Uses the CI/CD managed identity Terraform had already provisioned for exactly this (OIDC federation, no stored secret) -- but its Terraform-granted `AcrPush` alone wasn't enough for `az acr build` (confirmed: that needs ARM-level access to queue a build task, not just push/pull), so added two narrowly-scoped role assignments directly (Contributor on the registry only, Container Apps Contributor on the one Container App only; `az role assignment create` had an unrelated client-side bug for this resource type, worked via the Azure REST API directly). First real run failed with `AADSTS700213`: GitHub had started issuing this repo's OIDC tokens in a new immutable owner-id/repo-id subject format (a real, dated platform change, 2026-04-23 per GitHub's own changelog) that the Terraform-provisioned federated credential's classic-format subject no longer matched. Fixed the live credential with the real IDs from the failure's own error log, updated Terraform so it doesn't drift back, then re-ran the workflow twice (once right after the fix, once on the very next real push) -- both fully green: test, login, build, deploy, health check.

**SDK has no real auth beyond the Operator Key: RESOLVED.** Confirmed the server already supported scoped credentials the SDK simply never used (`POST /v1/auth/login` session tokens, `POST /v1/organization/api-keys` scoped API keys, both resolved identically via `Authorization: Bearer`). Added `Agent(bearer_token=...)` as the preferred alternative to `api_key` for every administrative call (`register`/`rotate_keys`/`retire`/`get_decision`), purely additive so every existing `api_key` integration keeps working unmodified. Renamed `HttpClient`'s internal `operator_auth` flag to `admin_auth`, since it no longer means "operator key specifically." Added real coverage (HttpClient-level header/precedence tests, one full Agent-level end-to-end test with a real `HttpClient` and fake `requests.Session`) and bumped 0.2.0 -> 0.3.0. `SDK_SECURITY.md` previously claimed a scoped-credential system "does not exist yet" -- already false before this change, now corrected and recommending `bearer_token` as the production default.

Three of the four P2 items are now closed. Only the production Postgres restore drill remains (see the table below), plus P3 (deliberately parked).

| Item | Verified current state | Fix |
|---|---|---|
| **Production Postgres restore drill** | A restore drill was performed and verified on staging (per Milestone-era reports). No repo evidence a production-specific drill has been run since the DNS cutover. Infra-only, **Unverified** from a repo pass; needs a direct check against the actual environment. | Run and document a restore drill against the production resource group specifically. |

---

## P3: Defer past v2, or accept as a known, disclosed gap

| Item | Status |
|---|---|
| **Legacy `documents` table has no org column** | Deliberately not fixed per Milestone 13's own verdict (table confirmed dead/empty, doesn't block Enterprise Knowledge work). A disclosed, accepted risk, not an active bug. Revisit only if Enterprise Knowledge work resurrects a path that writes to this table. |
| **Authority Builder discovery to enforcement auto-promotion** | Already deliberately deferred pending real pilot workflow evidence. Correct to leave open until a pilot exists to inform the design. |
| **Sales/legal/commercial collateral** (named pilot customer or LOI, formal security architecture doc, SOC2/ISO27001 roadmap, DPA template, enterprise FAQ, deployment/architecture decks) | **Not found in either repository.** Not re-checked today since this isn't code-verifiable. Flagging as still open per the last full audit; ownership sits outside engineering. |
| **API reference / Evidence-verification page framing** | Checked today and found **already correctly scoped**. `ApiReference.tsx` already links to the live, always-current reference rather than claiming completeness; `EvidenceVerification.tsx` already correctly separates "live today" (signature verification, export) from "planned" (offline/portable verification only). No action needed; earlier audits describing these as gaps are stale. |

---

## Already closed: verified today, don't re-open

- **Multi-org isolation tests exist and are real**: `test_multi_tenant_opa_isolation.py`, `test_multi_tenant_runtime_policy_isolation.py`, `test_organization_isolation.py`, `test_policy_simulator_multi_tenant.py`, `test_second_organization_onboarding.py`.
- **Website README** already reflects the current five-product framing (Runtime Authority, Authority Graph, Runtime Policies, Evidence Portal, Authorization Receipts, Insurance Portal). The "ten modules" naming an older audit flagged no longer exists anywhere in it.
- **Azure prod/staging parity**: `prod.tfvars` pins `prod-0c7672d`, a current, post-Milestone-15 image, not stale.
- Multi-tenant schema, Operator Key org-scoping, RBAC permission gates across every route, IDOR/unscoped-read gaps, real-decision per-condition explainability, the Rust/gRPC founder-bio claim, Azure DNS cutover, and today's demo-nav permission bug: all closed across Milestones 2, 3, 7, 9, 10, 11, 12, 15, and this session.

---

## Suggested order

1. **P0** is done (Render retired 2026-08-19).
2. **P1** is done (all six items closed 2026-08-19).
3. **P2** is done except one item: the production Postgres restore drill, which needs a direct check against the actual environment (SDK auth, backend CD, and Terraform state separation all closed 2026-08-19).
4. **P3** stays deliberately parked until v2 or until a pilot/customer forces the question. Building ahead of real signal here is exactly the kind of premature work the platform's own prior audits have repeatedly warned against.
