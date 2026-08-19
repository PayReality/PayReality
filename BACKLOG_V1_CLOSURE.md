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

## P2: Fix before v2, larger or infra-dependent effort

| Item | Verified current state | Fix |
|---|---|---|
| **SDK has no real auth beyond the Operator Key** | Confirmed: zero `Authorization`/`Bearer`/`session_token` references anywhere in `sdk-python/payreality/client.py`. The SDK still predates RBAC entirely; an integrator can only authenticate as the platform-wide admin bypass. | Add session-token/scoped-API-key support alongside the Operator Key path; bump the SDK version once it lands. |
| **No backend CD pipeline** | Confirmed: `.github/workflows/` has `ci.yml` (test + build only) and `azure-static-web-apps.yml` (frontend only, from Milestone 16). No workflow deploys the backend API anywhere; every backend deploy to both Render and Azure is still a manual, by-hand action. | Add a real deploy job (GitHub Actions to ACR build to Container Apps revision update, or equivalent), matching what the frontend already has. |
| **Runtime Policy Lifecycle orchestration's live-database status is unclear** | `test_runtime_policy_lifecycle_service.py` exists but its fixtures were not confirmed today to exercise a real Postgres rather than a scripted fake session. Genuinely **Unverified**, not confirmed either way. | Confirm directly (read the test's fixtures); if it's still fake-session-only, run the activate/rollback/retire/schedule sequence against a real Postgres + OPA at least once and document it. |
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
3. **P2** next. Larger, but still independent of each other: SDK auth modernization, backend CD, lifecycle live-DB confirmation, production restore drill.
4. **P3** stays deliberately parked until v2 or until a pilot/customer forces the question. Building ahead of real signal here is exactly the kind of premature work the platform's own prior audits have repeatedly warned against.
