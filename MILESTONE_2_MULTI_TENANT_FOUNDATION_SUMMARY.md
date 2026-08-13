# Milestone 2 — Multi-Tenant Foundation — Architecture Decision Record & Implementation Summary

**Status: Complete.** Phases A–C (Architecture Decision Record, below) were reviewed and Option 2 was confirmed. Phase D (Implementation) is now complete: 10 atomic commits, 304/304 tests passing (unit + real-OPA integration), zero regressions. See "Phase D — Implementation" near the end of this document for the full deliverable set (Files Changed, Test Report, Remaining Risks, Recommendation for Milestone 3).

**Roadmap reference:** `PAYREALITY_ENTERPRISE_HARDENING_PLAN.md` Milestone 2, item 3 (schema-level Runtime Policy multi-tenancy); `PAYREALITY_ENTERPRISE_V1_MASTER_ROADMAP.md` Security workstream; `MILESTONE_1_SECURITY_AUTHORIZATION_HARDENING_SUMMARY.md`'s own "Recommendation for Next Milestone."

---

## Phase A — Repository Dependency Analysis

Full per-table detail (model columns, every service function, every router endpoint, SDK/frontend/test coverage, and the exact migration that created or altered each table) is preserved in full in the research transcript this document was produced from, and is summarized in the table below. The single most important structural fact this analysis surfaced, cited with exact code locations, drives everything in Phase B:

> **There is exactly one compiled OPA bundle and exactly one OPA package for the entire deployment, today, unconditionally.** `Policy.__table_args__` (`server/app/db/models.py:221-234`) enforces `idx_policies_single_active` — a partial unique index allowing exactly one `status='active'` row **platform-wide**, not per organization. `runtime_policy_service.py`'s `_other_active_policies` (401-422) and `reconcile_opa_with_active_policies` (356-398) both query `RuntimePolicyRecord` filtered only by `status == 'active'`, **with no organization filter of any kind** — every organization's active policies are unconditionally unioned into one compiled bundle. `opa_client.py`'s `DATA_PATH` and every `upload_policy(...)` call site (`runtime_policy_service.py:397,576`) use the single fixed literal package name `"authorization"` — there is no per-tenant package, path, or namespace anywhere in the OPA integration.

### Table-by-table summary

| Table | `organization_id`? | Reachable org scope | Compiles into OPA? | Milestone 1 status |
|---|---|---|---|---|
| `runtime_policy_records` | **No** | None | **Yes — this is the compiled content** | Not touched (no org column exists to scope) |
| `simulation_scenarios` | No | Via `policy_key` only | No (dry-run only, never deployed) | Not touched |
| `runtime_policy_lifecycle_events` | No | Via `policy_key` only | No | Not touched |
| `policy_activation_schedules` | No | Via `policy_key` only | No (schedules an org-blind action) | Not touched |
| `policies` (compiled bundle pointer) | **No** | None | **Is** the compiled bundle | Not touched; the single-active-row constraint is table-wide |
| `authority_corpora` | **Yes** (nullable) | Direct | No (informational, pre-enforcement) | Fixed — org-scoped, tested |
| 8 Authority Graph sibling tables | No | Via `corpus_id` only | No | Fixed transitively (gated at corpus level) |
| `principals` | Yes (nullable) | Direct | No (referenced by `scope.principal`, not itself compiled) | Fixed — org-scoped, tested |
| `authorities` / `mandates` | No | Via `principal_id` OR `corpus_id` (two independent, non-cross-validated paths) | No | Not touched |
| `organizations` | — (is the tenant table) | — | No | Pre-existing |
| `evidence` | **Yes** (nullable, indexed) | Direct | No (post-decision record) | Fixed — org-scoped, tested, most mature isolation in the codebase |
| `policy_extraction_candidates` / `_uploads` | No | Via `corpus_id`/`upload_id` | No (pre-promotion) | Not touched |
| `agents` / `certificates` | No | Via `acting_for_principal_id` only | No | Not touched |

### The three independent, non-cross-validated paths to "organization"

The analysis surfaced that the platform does not have one canonical way to ask "what organization does this belong to" — it has (at least) three, which today happen to agree only because there is genuinely one organization in any current deployment:

1. **`Principal.organization_id`** — set at Principal creation/resolution.
2. **`AuthorityCorpus.organization_id`** — set at corpus creation, the scope Milestone 1 enforced.
3. **A new `RuntimePolicyRecord.organization_id`**, which does not exist yet and is exactly what this milestone must add.

`Authority.organization_id` doesn't exist either — it's reachable via **either** `principal_id` **or** `corpus_id`, and nothing in `ai_policy_builder_service.py`/`ai_authority_builder_service.py` checks that those two paths, when both present, agree. This is a real, if currently latent (single-org deployments can't expose it), design gap that Milestone 2 should close as part of establishing one canonical resolution path, not three.

---

## Phase B — Architecture Validation

### B1. How should Runtime Policies be isolated?

Three candidate approaches, in increasing order of isolation strength and implementation cost:

**Option 1 — Shared bundle, org-scoped compilation, incidental rule-level discrimination.** Add `organization_id` to `RuntimePolicyRecord`; scope `_other_active_policies`/`reconcile_opa_with_active_policies` to filter by it; each org's compile/deploy only ever unions *that org's own* active policies. The OPA package stays a single, shared `"authorization"` package — but is it uploaded as N org-scoped fragments concatenated together, or does each org's compile still produce and upload the *whole* shared package? Either way, tenant safety at evaluation time rests entirely on `input.agent.acting_for_principal_id` never coinciding across two organizations' policies — true today because Principal ids are UUIDs, but **not a structurally enforced guarantee**: nothing in `runtime_policy.validators` requires `scope.principal` to resolve to a real, org-checked Principal at all (it accepts any non-empty string, per Policy Studio's manual-authoring support). *Cheapest to build. Weakest formal guarantee. Leaves the "one org's compile error blocks another org's deploy" noisy-neighbor problem only partially addressed (better than today, since conflict detection is now org-scoped, but a shared-package upload still means one org's transient OPA unavailability affects all orgs simultaneously).*

**Option 1b — Shared package, but with a formally-enforced, compiler-generated organization guard.** Same schema change as Option 1, plus: `RuntimePolicy.scope` gains an explicit `organization_id` (threaded through from the authoring organization, not inferred from principal string matching), and `rego_generator.py`'s `generate_scope_block` emits an **explicit** `input.agent.organization_id == "<org>"` line on every rule, compiled in at generation time. `intent_service`/`authority_context_service` must resolve and pass `agent.organization_id` into `build_opa_input` (the data is already available via the existing Principal lookup — this is a plumbing change, not a new lookup). This turns tenant isolation from an incidental byproduct of UUID uniqueness into a **structural, tested Rego invariant**, while keeping ops simplicity (one package, one reconciliation call). *Moderate cost. Strong formal guarantee at the evaluation layer. Still shares one OPA package operationally — one org's malformed policy still blocks the whole package's compile/upload for every org until fixed, and OPA package-level metrics/logs are not naturally separable per tenant.*

**Option 2 — One compiled bundle and one OPA package per organization.** `RuntimePolicyRecord` gets `organization_id`; the `policies` table's single-active-row constraint becomes per-organization (`idx_policies_single_active` keyed on `(organization_id)` where `status='active'`, not on `status='active'` alone); OPA package naming becomes `payreality.authorization.<organization_id>` (or equivalent); `PolicyStore.get_active()` becomes `get_active(organization_id)`; `decision_engine.evaluate()` takes an `organization_id` parameter; `reconcile_opa_with_active_policies` iterates every organization and pushes N independent packages. Compile, conflict-detection, deploy, and rollback for one organization become **completely independent operations** from every other organization's — no shared state, no shared failure mode, no noisy-neighbor risk of any kind. *Highest cost (touches the Decision Engine's own Protocol signature, the hottest path in the system). Strongest possible guarantee: independently auditable, independently replayable, independently rolled-back per tenant — exactly the isolation story a security-conscious enterprise buyer's procurement review will test for directly (per the CIO-lens findings already synthesized in `PAYREALITY_ARCHITECTURE_REVIEW_AND_ROADMAP.md`).*

**Recommendation: Option 2**, with Option 1b as the closest fallback if a phased rollout is preferred. Reasoning is given in Phase C.

### B2. How should OPA evaluate tenants — one package per tenant, or one package containing all tenants?

Directly follows from B1. **One package per tenant** (Option 2's shape), for three concrete reasons found in this analysis, not as a general preference:

1. **`idx_policies_single_active` already assumes "one active thing" as its unit of truth** — extending that unit to be "one active thing per organization" is a smaller conceptual leap than retrofitting tenant-awareness onto a single shared thing that was never designed to hold more than one coherent policy set.
2. **Compile-time conflict detection (`compiler_v2._policy_conflicts`) groups by `(principal, action)`** — a shared package makes this grouping tenant-blind by construction; if any two organizations' policies happen to reference the same `scope.principal` string (a real risk for manually-authored, non-UUID principal names), the compiler will flag a false cross-tenant conflict and **block both organizations' deploys**, an availability bug directly caused by the shared-package model, eliminated entirely by per-tenant packages.
3. **`reconcile_opa_with_active_policies` runs once at process startup** (`main.py`'s lifespan hook) and pushes the *entire* active set. Under a shared package, a single malformed or newly-conflicting policy from any one organization can, in principle, prevent this reconciliation from succeeding for every organization simultaneously (recompilation is all-or-nothing per package). Per-tenant packages make this failure mode organization-local.

### B3. Operator Key — disappear, org-scoped, or platform-admin only?

**Recommendation: neither disappear nor become org-scoped — become explicitly platform-admin-only.**

- **Disappear** is rejected for this milestone: the SDK's default onboarding flow depends on it today (`sdk-python/payreality/agent.py`'s `_resolve_principal_id` passes `operator_auth=True`), and the SDK's own modernization to support scoped credentials is `PAYREALITY_ENTERPRISE_V1_MASTER_ROADMAP.md`'s **Milestone 6**, explicitly sequenced after this one. Removing the Operator Key now would break every existing integration with no replacement in place — the opposite of the "favor... long-term maintainability over short-term convenience" instruction governing this milestone.
- **Organization-scoped** (one Operator Key per org) is rejected because it doesn't address the actual defect. The Operator Key's problem was never *which* organization it resolves to — it's that it is a **full RBAC bypass that never checks a permission at all** (`dependencies.py:73-78`, `hmac.compare_digest` against one secret, `return` with no permission check whatsoever). Scoping it per-organization would just give every organization its own copy of the same all-or-nothing bypass, reproducing the identical anti-pattern once per tenant instead of once platform-wide — no real security improvement, and it multiplies the number of unscoped-admin credentials in existence.
- **Platform-admin-only** is recommended: keep exactly one Operator Key, but change what it *means*. It stops being "the default path a normal customer integration uses" (that responsibility moves to scoped session/API-key auth, per Milestone 6) and becomes an explicitly-labeled, narrowly-documented credential for legitimate cross-organization platform administration (initial org bootstrap, break-glass support access) — the same shape "break-glass admin access" takes in most real multi-tenant SaaS platforms: rare, intentionally cross-tenant-capable *by design*, never the primary integration path.

**A concrete, necessary consequence of this decision, in scope for Phase D:** `get_current_organization`'s Operator Key branch (`dependencies.py:143-151`) currently resolves to *"whichever organization was created first"* — silently and unconditionally. Once a second real organization exists, this becomes actively wrong: a platform admin using the Operator Key against an org-scoped endpoint would silently act on the wrong organization, not the one they intend. This must change to require an **explicit** target organization when the Operator Key is used against any org-scoped endpoint (e.g., a required `X-PayReality-Organization-Id` header on that path only), removing the implicit "first org" default entirely. This is a small, well-scoped piece of Phase D's implementation, not a new architectural direction.

### B4. Must Authority Intelligence → Runtime Policies → OPA Bundles become organization-specific end to end?

**Yes, and the dependency analysis found a concrete break in that chain today, not just a theoretical gap.** `AuthorityCorpus.organization_id` is set at extraction time and enforced by Milestone 1. But the moment a candidate is promoted — `ai_policy_builder_service.promote_candidate` → `runtime_policy_service.create_policy` — the resulting `RuntimePolicyRecord` has **no column to receive that organization_id at all**. Organization lineage that Authority Intelligence correctly established is **silently dropped** at exactly the handoff point into Runtime Policies.

The required lifecycle, once B1's schema change lands:

1. Authority Intelligence establishes `organization_id` on the corpus (already true, already enforced).
2. Promotion (`promote_candidate` → `create_policy`) must **thread** that same `organization_id` onto the new `RuntimePolicyRecord` — a direct, mechanical fix once the column exists.
3. Every Runtime Policy Lifecycle table (Phase 5: lifecycle events, activation schedules) must carry the same `organization_id`, inherited from the `RuntimePolicyRecord` they reference — not re-derived independently.
4. Compilation (`_other_active_policies`, `reconcile_opa_with_active_policies`) filters/groups by that `organization_id`.
5. The OPA Bundle becomes organization-specific per B1/B2's recommendation.
6. Evidence (already organization-scoped, resolved independently via `Agent → Principal`) should be **cross-validated** against the policy's own `organization_id` at decision time — today these are two independent resolution paths that happen to agree only because there's one real organization; Phase D should add a check (or at minimum a logged warning) if a decision's Evidence-org and the policy-that-decided-it's org ever disagree, rather than silently trusting they always will.

### B5. Migration Strategy

**Principles, all directly inherited from this codebase's own established conventions** (every prior org-scoping migration in this repository — `authority_corpora`'s Stage A migration, `evidence`'s Phase 5 chaining migration — added `organization_id` as **nullable**, additive, never rewriting existing rows' meaning):

1. **Add `organization_id` (nullable) to `runtime_policy_records`, `simulation_scenarios`, `runtime_policy_lifecycle_events`, `policy_activation_schedules`, and `policies`.** Nullable specifically so the migration itself never fails or blocks on existing data, matching the exact pattern already used everywhere else in this codebase.
2. **Backfill every existing row to the single, already-bootstrapped Organization.** Every current deployment is genuinely single-tenant (confirmed repeatedly across every prior architecture document); backfilling to "the one org that already exists" is lossless and requires no judgment calls, because there is exactly one correct answer today.
3. **Widen `idx_policies_single_active` from table-wide to per-organization** (unique on `organization_id` where `status='active'`). This is the one migration step that changes a structural invariant rather than just adding a column — but because step 2 guarantees exactly one organization exists at migration time, the new per-organization constraint and the old table-wide constraint are **mathematically equivalent** for any deployment migrating today. The risk this step protects against is entirely in the future (a second organization being onboarded), not in the migration itself.
4. **Never delete, rewrite, or renumber existing history.** Every retired `RuntimePolicyRecord` version, every `RuntimePolicyLifecycleEvent`, every `Evidence` row stays exactly as it is; only the new nullable column changes, backfilled once. This preserves policy history, Evidence, and auditability by construction — the migration adds information, it never removes or reinterprets any.
5. **Add a cross-validation check (B4, item 6), not a migration** — since Evidence already has organization_id and it already agrees with everything else in a single-org deployment, there's nothing to migrate there; the new work is a runtime consistency check guarding against *future* drift, not a data change today.
6. **Only after step 3 lands should the Render→Azure Postgres data migration (Master Roadmap, Milestone 3) be executed** — exactly the one hard cross-workstream dependency already named in `PAYREALITY_ENTERPRISE_V1_MASTER_ROADMAP.md`'s Execution Strategy, reconfirmed here.

---

## Phase C — Architecture Review

### Current architecture

One shared, tenant-blind compiled bundle (`policies`, one active row platform-wide) and one shared, tenant-blind OPA package (`payreality.authorization`). Every organization's active `RuntimePolicyRecord`s are unconditionally unioned at every compile. Tenant safety at evaluation time is entirely incidental, resting on Principal-UUID uniqueness that is not structurally enforced. Authority Intelligence's organization lineage is silently dropped at the promotion handoff into Runtime Policies. The Operator Key resolves to an implicit, increasingly-wrong "first organization" default.

### Proposed architecture (recommended: Option 2 from B1/B2)

`organization_id` added to every Runtime Policy-adjacent table named in B5; one compiled bundle and one OPA package **per organization**; `PolicyStore`/`decision_engine.evaluate()` take an explicit organization parameter; the Operator Key becomes an explicit, narrowly-scoped platform-admin credential with no implicit default organization; Authority Intelligence's organization lineage is threaded, unbroken, through promotion and into the compiled bundle.

### Advantages

- A **formal**, not incidental, tenant-isolation guarantee at every layer — the exact claim an enterprise security review will test directly.
- Eliminates the noisy-neighbor compile/conflict/deploy failure mode entirely, not just partially.
- Each organization's Runtime Authority becomes independently auditable, independently replayable, and independently rolled back — a stronger, simpler story to document for a buyer than "shared infrastructure with an internal guard."
- Closes the concrete Authority-Intelligence-to-Runtime-Policy org-lineage break found in this analysis, not just the schema gap.

### Risks

- **Architecture**: touches `decision_engine.evaluate()`'s own Protocol signature — the hottest path in the system and the one place this whole engagement has repeatedly said must not be redesigned casually. Mitigated by keeping the *algorithm* (fail-closed, ALLOW/DENY/HUMAN_REVIEW) completely unchanged; only its inputs gain one new, required parameter.
- **Backward compatibility**: every existing caller of `PolicyStore.get_active()`/`evaluate()` must be updated to pass an organization_id — a real, mechanical, but non-trivial ripple through `intent_service.py` and every test double implementing the `PolicyStore`/`OpaClient` Protocols.
- **Migration**: the `idx_policies_single_active` widening (B5, step 3) is the one step with any real risk, and only a future risk (a second organization), not a migration-time one, per the reasoning in B5.
- **Security**: none identified beyond what's already being fixed — this change strictly narrows access, it does not widen it anywhere.
- **Performance**: N OPA packages instead of 1 means N reconciliation pushes at startup instead of 1 (linear in tenant count, not a scaling concern at pilot scale of a handful of customers; worth a named, deferred question — not a blocker — if tenant count ever reaches the "thousands" scale the Enterprise Knowledge Resolution vision document already flags as its own open scaling question).

### Migration complexity

**High** for the Decision Engine/OPA-plumbing changes (B1 Option 2, B2); **Low** for the schema/backfill migration itself (B5) given the single-organization-today guarantee. The two are independent risk profiles and should be sequenced and tested separately in Phase D, not treated as one undifferentiated change.

### Rollback strategy

Every schema addition in B5 is nullable and additive — a rollback is a straightforward reverse migration with no data loss, following the exact pattern already used and verified offline (`alembic ... --sql`, both directions) for every prior migration in this program. The Decision Engine/OPA plumbing change (B1/B2) should be built and merged behind a code path that can be reverted to the current single-package behavior independently of the schema migration, so a problem discovered in the evaluation-layer change does not force reverting the (lower-risk) schema work too.

### Recommendation

**Adopt Option 2** (B1/B2): per-organization compiled bundle and OPA package, Operator Key becomes platform-admin-only (B3), Authority Intelligence's organization lineage threaded unbroken into Runtime Policies (B4), and the additive, nullable, single-org-safe migration described in B5.

If a phased rollout is preferred over building the full per-organization OPA package mechanism in one pass, **Option 1b is the recommended intermediate step**, not Option 1 — Option 1 leaves tenant safety incidental, which this analysis found to be a real, if currently latent, gap rather than a theoretical one (manually-authored, non-UUID `scope.principal` values are explicitly supported today).

---

**Phase C's STOP point held**: no schema migration, code change, or Phase D work occurred until this recommendation was reviewed. The user confirmed both open questions together with a single "yes": (1) Option 2 over Option 1b, and (2) the Operator Key becoming platform-admin-only, including the concrete consequence that its "resolves to whichever organization was created first" default would be removed and replaced with a required explicit target organization.

---

## Phase D — Implementation

### Implementation Summary

All ten planned commits landed, in the sequence below. Two deviations from the plan, both disclosed at the time:

- **Commits 4a/4b were planned as separate CRUD-vs-compile/deploy commits and merged into one** (Commit 4): `compile_policy`/`dry_run_policy`/`deploy_policy`/`diff_versions` all call `get_latest`/`_other_active_policies` internally, so splitting the CRUD signature change from the compile/deploy signature change would have produced a commit that imports fine but breaks at call time — violating "every commit independently compiles and, where meaningful, is independently testable." Disclosed explicitly in Commit 4's own message rather than silently merged.
- **A design decision found during Commit 6 lowered the risk Phase C's own Risks section flagged**: the ADR's Risks section said this touches `decision_engine.evaluate()`'s own Protocol signature. In fact, `_DbPolicyStore`/`_EngineOpaClient` (`intent_service.py`) are concrete adapters constructed fresh per request, so organization binding happens entirely at that construction site — `domain/decision/engine.py`'s pure `PolicyStore`/`OpaClient` Protocols were never touched. This is a strictly better outcome than the ADR anticipated, not a deviation from it.

Beyond the ADR's own plan, three genuine cross-tenant leaks were found and fixed while wiring the lifecycle service (Commit 7) and safety checks (Commit 8) — not named in Phase A's dependency analysis, because they were bugs in code that didn't exist yet at analysis time:

1. `search_policies` and `get_dashboard` loaded every organization's `RuntimePolicyRecord` rows unconditionally.
2. `get_timeline`/`cancel_schedule` had no organization check at all — an IDOR, not merely a missing filter.
3. Runtime Policy safety checks (`_other_active_runtime_policies`, `_check_broken_inheritance`, `_check_missing_principal`) evaluated a candidate against every OTHER organization's active policies and Principal rows — the exact "noisy neighbor" scenario B2 named for OPA compilation, but for the safety-check layer, which B2's own analysis hadn't covered.

### Commits

| # | Commit | Summary |
|---|---|---|
| 1 | `2817b53` | Migration `a7d3e9f2c6b1`: additive, nullable `organization_id` on `policies`/`runtime_policy_records`/`simulation_scenarios`/`runtime_policy_lifecycle_events`/`policy_activation_schedules`; backfill to the platform's one bootstrapped Organization; widen `idx_policies_single_active` → `idx_policies_single_active_per_org`. Verified offline, both directions (`alembic ... --sql`), no live Postgres reachable in this environment. |
| 2 | `3053469` | Promote `dry_run.py`'s private `_rewrite_package` to a public `bundle_builder.retarget_package` — the mechanism per-organization packaging reuses, generalized rather than duplicated. Fixes the cross-module private-helper import `batch_evaluator.py` had taken on it. |
| 3 | `0b21889` | `opa_client.py`: `org_package_path`/`org_policy_id`/`org_data_path` naming helpers; `HttpOpaClient.query` gains an optional `data_path` override. |
| 4 | `05a3ce4` | `runtime_policy_service.py` becomes fully organization-aware: every CRUD/compile/deploy/diff/reconcile function takes `organization_id`; `organization_id=None` is its own valid, consistent legacy scope. Forced immediate callers fixed in the same commit (`agents.py`, `ai_policy_builder_service.promote_candidate` + its router, `CrossOrganizationPromotionError`). `routers/runtime_policies.py` and `runtime_policy_lifecycle_service.py` explicitly disclosed as NOT yet updated. |
| 5 | `dbecad5` | `routers/runtime_policies.py`: every endpoint depends on `get_current_organization`, threads `organization.id` through. |
| 6 | `afeb201` | `intent_service.py`: `_DbPolicyStore`/`_EngineOpaClient` bound to the acting Principal's `organization_id` at construction time inside `submit_intent` — the actual decision-time path, not just authoring/CRUD. |
| 7 | `03d90b3` | `runtime_policy_lifecycle_service.py` + `routers/runtime_policy_lifecycle.py`: every function threads `organization_id`; fixes the three leaks named above; `record_lifecycle_event` gains an optional `organization_id` parameter. |
| 8 | `001a00d` | `runtime_policy_safety_checks.py`: `run_safety_checks` and its DB-backed checks scoped to `organization_id`, closing the safety-check noisy-neighbor gap. |
| 9 | `ba1ff70` | `dependencies.py`: Operator Key becomes platform-admin-only — `get_current_organization`'s Operator Key branch now requires an explicit `X-PayReality-Organization-Id` header; the "first organization created" default is removed entirely. |
| 10 | `3d434c7` | New test coverage: `test_multi_tenant_runtime_policy_isolation.py` (fake-session, SQL-statement assertions, following this codebase's established convention for CRUD functions that require a live database) and `test_multi_tenant_opa_isolation.py` (real, ephemeral OPA server — two organizations sharing an identical `scope.principal`/`action`, one ALLOW and one DENY, proven to evaluate independently; the legacy shared package proven unaffected). |
| — | `6d0b806` | Documentation: `SPECIFICATION/02,05,07,08,09,14,16` updated to reflect the above; one stale docstring fixed in `routers/ai_authority_builder.py`. |

### Architecture Decisions (beyond the ADR above)

- **`organization_id=None` as its own valid, consistent scope**, not an error — matches `evidence_service.verify_chain`'s existing convention, and is why 282 of the pre-existing 282 unit tests needed zero changes (only the 2 whose function signatures/query shapes directly changed were touched).
- **Package retargeting happens only at upload time**, never inside `compiler_v2`/`bundle_builder.build_bundle`, which still always emit the literal `package payreality.authorization` unchanged — keeping the Compiler V2 pipeline itself genuinely untouched, per the milestone's Architecture Rules.
- **Version numbering on `Policy` stays global**, not per-organization — it's a monotonic bookkeeping counter with no correctness dependency on being organization-local; scoping it would have been unnecessary complexity.
- **`get_timeline` verifies organization ownership via `get_latest`, then reads events by `policy_key` alone**, not re-filtered by `organization_id` — because lifecycle events written by `runtime_policy_service.py`'s own CRUD functions don't yet stamp `organization_id` on the event row itself (see Remaining Risks), filtering the event query directly would have hidden most of a policy's real history.

### Migration Strategy

Exactly as specified in B5 above, executed without deviation: additive/nullable columns, backfill to the one existing Organization, per-organization uniqueness constraint (mathematically equivalent to the old table-wide one for any single-organization deployment), no history rewritten. Verified offline in both directions; no live Postgres reachable in this development environment, consistent with every prior migration in this program.

### Test Report

- **304/304 tests pass** (290 unit + 14 integration), zero regressions, run repeatedly throughout Phase D after every commit.
- **6 new unit tests** (`test_multi_tenant_runtime_policy_isolation.py`): `list_latest_policies`/`get_latest`/`list_versions`/`get_version` assert the compiled SQL statement carries the `organization_id` filter; `create_policy` asserts the stamped value; `edit_policy` asserts the new version inherits `latest.organization_id`, never a different caller-supplied one.
- **2 new integration tests** (`test_multi_tenant_opa_isolation.py`), against a real, ephemeral OPA server (not mocked): two organizations sharing an identical `scope.principal`/`action` — one ALLOW, one DENY — evaluate completely independently once uploaded under their own per-organization package; the legacy `organization_id=None` shared package is proven unaffected by, and coexisting alongside, per-organization packages in the same OPA instance. Both tests clean up every policy id they upload, verified to pass regardless of file execution order against the shared, session-scoped OPA fixture.
- **2 new tests** in `test_runtime_policy_safety_checks.py` covering the cross-organization Principal case for `_check_missing_principal`/`_check_broken_inheritance`.
- `compile_policy`/`deploy_policy`/`dry_run_policy` remain outside fake-session unit test coverage, per this codebase's own pre-existing, established convention (`test_runtime_policy_service_diff.py`'s docstring: they compose `compiler_v2` and genuinely require a live database session) — their real-OPA behavior is what `test_multi_tenant_opa_isolation.py` proves instead.
- Migration verified offline (`alembic upgrade/downgrade ... --sql`), both directions, no live Postgres reachable in this environment — consistent with every prior migration in this program.

### Files Changed

**New:** `server/alembic/versions/a7d3e9f2c6b1_multi_tenant_runtime_policy_foundation.py`, `server/tests/unit/test_multi_tenant_runtime_policy_isolation.py`, `server/tests/integration/test_multi_tenant_opa_isolation.py`.

**Modified:** `server/app/db/models.py`, `server/app/domain/compiler_v2/bundle_builder.py`, `server/app/domain/compiler_v2/dry_run.py`, `server/app/domain/policy_simulation/batch_evaluator.py`, `server/app/opa_client.py`, `server/app/services/runtime_policy_service.py`, `server/app/routers/runtime_policies.py`, `server/app/services/intent_service.py`, `server/app/services/runtime_policy_lifecycle_service.py`, `server/app/services/runtime_policy_lifecycle_events.py`, `server/app/routers/runtime_policy_lifecycle.py`, `server/app/services/runtime_policy_safety_checks.py`, `server/app/dependencies.py`, `server/app/main.py`, `server/app/routers/agents.py`, `server/app/services/ai_policy_builder_service.py`, `server/app/routers/ai_policy_builder.py`, `server/app/routers/ai_authority_builder.py` (docstring only), `server/tests/unit/test_policy_compilation_ordering.py`, `server/tests/unit/test_runtime_policy_lifecycle_service.py`, `server/tests/unit/test_runtime_policy_safety_checks.py`, plus the seven `SPECIFICATION/*.md` files listed in the documentation commit above.

### Remaining Risks

All disclosed at the commit that introduced them, consolidated here:

1. **Frontend, Python SDK, and `scripts/smoke_test.py` are not updated for the platform-admin-only Operator Key.** All three currently call org-scoped endpoints with the Operator Key and no `X-PayReality-Organization-Id` header, and will receive `organization_id_required_for_operator_key` (400) until updated. Confirmed acceptable via explicit user decision before Commit 9 landed; deferred to follow-up work outside this backend-architecture milestone's scope (likely Milestone 6, SDK & Integration Modernization).
2. **Lifecycle events written by `runtime_policy_service.py`'s own CRUD functions** (created/edited/submitted/approved/rejected/compiled) **still pass no `organization_id`** to `record_lifecycle_event`, even though `record_lifecycle_event` now accepts one and every call site added in this milestone (`runtime_policy_lifecycle_service.py`) passes it. `get_timeline`'s design (verify ownership via `get_latest`, then read events by `policy_key` alone) already accounts for this, so it is not a functional gap for that read path — but the event rows themselves remain unstamped, a narrower loose end than it might first appear.
3. **The mutating Authority Builder endpoints** (`resolve_principal`, `resolve_relationship`, `activate_relationship`, `answer_question`, `approve_graph`) still don't verify their target row's organization, only that the caller holds `AUTHORITY_REVIEW` — a Milestone 1-era gap, unrelated to Runtime Policies, not addressed by this milestone because it was out of this milestone's scope.
4. **`docs/openapi.json` is stale** — regenerating it produced a ~12,000-line diff far larger than this milestone's actual router changes explain, indicating staleness that predates this milestone. Not regenerated here to avoid bundling unrelated churn into this milestone's commits; flagged as its own follow-up.
5. **No live Postgres reachable in this development environment**, consistent with every prior phase of this entire engagement — the migration and every DB-backed function are verified via offline `alembic --sql` and fake-session unit tests, never against a real deployed database. This is a pre-existing environmental constraint, not something Milestone 2 introduced.
6. **`AuthorityCorpus.organization_id`/`Principal.organization_id`/`RuntimePolicyRecord.organization_id` are now cross-validated at exactly one point** (`ai_policy_builder_service.promote_candidate`'s `CrossOrganizationPromotionError`) — Phase B4's item 6 (cross-validating Evidence's independently-resolved organization against the policy-that-decided-it's organization) was not implemented; Evidence's own organization resolution (`Agent → Principal`) and Runtime Policy's organization remain two independent paths that happen to agree only because a Principal's organization and the policy governing it are not currently allowed to diverge (the safety checks added in Commit 8 enforce exactly this at activation time) — a logged-warning-level cross-check, as B4 itself proposed as the minimum bar, was judged unnecessary given Commit 8's stronger, fail-closed enforcement, but is named here for completeness rather than silently dropped.

### Recommendation for Milestone 3

Per `PAYREALITY_ENTERPRISE_HARDENING_PLAN.md`'s naming and this milestone's own Scope Rules ("do NOT begin Azure migration... unless required to complete Milestone 2" — nothing here required it), the next milestone is **Milestone 3 — Azure Completion & Cutover Readiness**. This milestone's own B5 §6 named the one hard cross-workstream dependency already on record: the Render→Azure Postgres data migration should not be executed until this milestone's schema work (the per-organization `idx_policies_single_active_per_org` widening) had landed — it now has. Milestone 3 can proceed without further Runtime Policy schema changes.

Not proceeding into Milestone 3 without explicit go-ahead, per the Scope Rules governing this milestone.
