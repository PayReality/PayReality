# Multi-Tenant Architecture Verification — Pre-Milestone 3

**Type:** Read-only verification. No production code was modified to produce this report, per the Scope Rules governing this pass. Two direct code-read spot-checks were performed by the lead verifier in addition to five independent adversarial sub-audits; every finding below is backed by an exact file:line citation, not by re-stating prior documentation.

**Scope:** Everything Milestone 1 (Security & Authorization Hardening) and Milestone 2 (Multi-Tenant Foundation) claimed to fix, plus every adjacent subsystem named in the verification brief, whether or not either milestone touched it.

---

## Executive Summary

Milestone 2's own claim — that Runtime Policies, RuntimePolicyRecord/Policy/lifecycle/schedule tables, and OPA packages are now organization-isolated — **holds up under adversarial re-verification**, with one confirmed authorization gap (`process_due_schedules`, see below) and a handful of narrower, currently-unreachable defense-in-depth gaps. That specific, scoped claim is true.

The broader question this verification was actually asked — **"is the platform now genuinely multi-tenant, ready to build more on top of"** — is **not** true today. This audit found five items that meet the BLOCKER bar (would let one tenant read, write, or forge audit records for another tenant's data, or crash a real endpoint), all pre-existing gaps that Milestones 1 and 2 either didn't touch or only partially closed:

1. **Five mutating Authority Builder endpoints** (`resolve_principal`, `resolve_relationship`, `activate_relationship`, `answer_question`, `approve_graph`) and one read endpoint (`get_principal_candidates`) have **no organization check at all** — a known gap named in `SPECIFICATION/14_SECURITY_MODEL.md` §14.6 and never actually fixed, confirmed still true against current code.
2. **The single-document AI Policy Builder pipeline has no organization concept whatsoever** — no column on `PolicyExtractionUpload`/`PolicyExtractionCandidate`, no auth on five read endpoints, and the one cross-org guard that exists (`CrossOrganizationPromotionError`) structurally cannot fire for it.
3. **`GET /v1/evidence/chain/verify` crashes (`TypeError`) for any organization with at least one Evidence record** — `verify_chain` calls `verify_evidence(db, record.id)` with a missing required `organization_id` argument. Confirmed by direct code read; zero test coverage exists for this endpoint.
4. **The Agent Detail Page's backend** (`GET /v1/agents/{id}`, `GET /v1/agents`) has no authentication or organization scoping at all, exposing another tenant's agents, decisions, evidence summaries, and audit events.
5. **There is no way to create a second Organization through the running application.** `Organization(...)` is constructed in exactly one place in the entire codebase — a startup-only bootstrap hook that only ever looks at "the oldest org." No API endpoint, SDK method, or frontend flow creates one. Milestone 2 built the isolation plumbing for N tenants; nothing in this codebase can onboard tenant #2.

Separately, Azure infrastructure readiness is **not blocked** by anything Milestone 2 introduced — Postgres, Container Apps, Key Vault, Managed Identity, Monitoring, Backups/DR, and Networking all check out. But two live, already-shipped Azure integrations (Blob Storage, AI Search — Authority Intelligence's document/vector store) have **zero organization scoping**, a gap already self-documented in `AUTHORITY_INTELLIGENCE_PHASE2_VALIDATION_REPORT.md` as unsafe "the moment a second organization is onboarded" — which is precisely the state Milestone 2 was meant to enable.

**Final verdict: Milestone 2's specific scope is verified sound. The platform as a whole is not yet genuinely, safely multi-tenant. See Phase 6 for the full answer to "would you approve beginning Milestone 3" — the answer is nuanced, not a bare yes.**

---

## Phase 1 — Repository Audit

Five independent adversarial sub-audits were run in parallel, each with instructions to distrust prior documentation and verify directly against current code:

| Audit | Files/subsystems covered |
|---|---|
| A — Identity & Authority Graph | `dependencies.py`, every router in `server/app/routers/` (grep sweep for client-supplied `organization_id`), all 22 endpoints in `ai_authority_builder.py`, `ai_authority_builder_service.py` traversal functions |
| B — Runtime Policy + OPA | `runtime_policy_service.py`, `runtime_policy_lifecycle_service.py`, `runtime_policy_safety_checks.py`, both routers, `opa_client.py`, `bundle_builder.py`, `compiler_v2.py`, `dry_run.py`, `batch_evaluator.py`, `intent_service.py` — read in full |
| C — Evidence + AI Policy Builder | `evidence.py`, `evidence_service.py`, `ai_policy_builder.py`, `ai_policy_builder_service.py`, `agents.py`, `document_service.py` |
| D — SDK + platform-global state | `sdk-python/payreality/*.py`, `scripts/smoke_test.py`, frontend `apiClient.ts`/`OperatorKeyField.tsx`, full `server/app/` grep for background jobs/caches/module-level state, `config.py`, `main.py` lifespan |
| E — Azure + migration readiness | `AZURE_MIGRATION/` directory, Terraform modules, `authority_intelligence_service.py`, `azure_foundry_provider.py`, `observability.py`, the Milestone 2 migration file |

Two claims from those audits were independently re-verified by direct code read before inclusion in this report (both confirmed true):

- `evidence_service.py:140`: `valid, _ = verify_evidence(db, record.id)` — `verify_evidence`'s signature (`evidence_service.py:64`) is `verify_evidence(db, evidence_id, organization_id)` with no default. This is a guaranteed `TypeError` on the first loop iteration whenever `records` is non-empty. `grep -rn "verify_chain" tests/` returns nothing — no test exercises this endpoint with data.
- `routers/ai_authority_builder.py:444-449`: `approve_graph`'s signature is `(corpus_id, body, db, session_user)` — confirmed no `Depends(get_current_organization)`, no `_authorized_corpus`.
- `grep -rn "Organization(" server/app` returns exactly one hit outside the model definition: `organization_service.py:31`, inside `ensure_owner_bootstrapped`.
- `domain/rbac/permissions.py:81-95`: confirmed `Role.OWNER` and `Role.GOVERNANCE_ADMIN` — ordinary per-tenant roles — both hold `RUNTIME_POLICY_PUBLISH`, the sole gate on `process_due_schedules`.
- `grep -n "organization_id" services/authority_intelligence_service.py` returns **zero matches** in the entire file.

No platform-global state beyond what's documented below was found in a full-tree grep for `lru_cache`, module-level `dict()`/`{}`/`set()`, or singleton clients.

---

## Phase 2 — Multi-Tenant Verification

### Identity

**PASS.** Every normal mutation/read path derives organization identity exclusively from `get_current_organization` (session/API key → `resolve_organization_id_for_token`, never client input) or from a resolved `Principal`/`Agent` chain. `CreatePrincipalRequest.organization_id` is accepted in the request body but explicitly discarded (`principals.py`, confirmed via comment and code). `promote_candidate` is the one place two independent organization sources are actually cross-validated (`CrossOrganizationPromotionError`).

One deliberate, documented exception: the Operator Key's `get_current_organization` branch takes an explicit `X-PayReality-Organization-Id` header — by design (platform-admin credential, Milestone 2), not client-spoofing of a derived identity.

One narrower exception, WARNING not BLOCKER: `GET /v1/evidence/chain/verify` takes `organization_id` as a bare, unauthenticated query parameter. This is an intentional, documented public/credential-free endpoint (third-party auditors verifying chain integrity without credentials) and its response schema (`ChainVerificationResponse`) was independently confirmed to return only hashes/UUIDs/counts, never payload content. It is also currently non-functional (see Evidence, below).

### Runtime Authority / Runtime Policies

**PASS, with one confirmed WARNING.** Every function across `runtime_policy_service.py`, `runtime_policy_lifecycle_service.py`, and `runtime_policy_safety_checks.py` takes and correctly filters by `organization_id`; `_other_active_policies` and `reconcile_opa_with_active_policies` were independently re-read and confirmed to filter by `organization_id` today, not merely per the summary's claim. `reconcile_opa_with_active_policies` iterates every organization's active set and pushes to that organization's own package — confirmed correct.

**Confirmed gap:** `POST /v1/runtime-policy-lifecycle/process-due-schedules` (`routers/runtime_policy_lifecycle.py:391-400`) has no `get_current_organization` dependency, gated only by `Permission.RUNTIME_POLICY_PUBLISH` — held by the ordinary per-tenant `Role.OWNER`/`Role.GOVERNANCE_ADMIN` roles, not restricted to the platform-admin Operator Key. Any tenant's own admin, using their own session token, can trigger this endpoint, which executes **every organization's** due schedules, not just their own. The per-schedule org-threading inside the function is itself correct (each schedule's own `organization_id` is used) — this is an authorization-boundary bug (wrong gate for a platform-wide action), not a data-mixing bug.

Narrower, currently-unreachable (policy_key/Principal ids are server-generated UUIDs, never client-chosen) defense-in-depth gaps also found: `diff_versions`'s `affected_agents` query, `resolve_mandate_ids`/`resolve_enterprise_system`, `effective_status`'s newer-active lookup, and `uq_runtime_policy_records_key_version`'s DB constraint all lack an explicit `organization_id` predicate. None are exploitable today; all break the otherwise-universal per-org-filter pattern and are worth closing opportunistically.

### OPA

**PASS.** `org_package_path`/`org_policy_id`/`org_data_path` are used consistently everywhere an org-scoped package/query-path is needed; the only remaining literal `payreality.authorization` usages are the intentional legacy-scope constant and `build_bundle`'s pre-retarget placeholder. `HttpOpaClient` has no caching or module-level mutable state — every call is a fresh request. `dry_run.py`/`batch_evaluator.py` use a disjoint naming prefix (`payreality.dryrun.*`/`payreality.batch.*`) that cannot collide with a real org package name. Package isolation reasoning holds under standard OPA semantics (each `package` declaration is an independent namespace; querying a child data path never surfaces a sibling package's rules). Verified two organizations sharing an identical `scope.principal`/`action`, one ALLOW and one DENY, evaluate independently against a real (not mocked) OPA server in `test_multi_tenant_opa_isolation.py` — this audit did not need to re-run that test to trust it, since the mechanism it tests (namespace disjointness) was independently confirmed by code read.

### Authority Intelligence

**WARNING → BLOCKER depending on deployment.** The multi-document AI Authority Builder's *read* surface (12 of 22 endpoints, everything gated by the Milestone-1 `_authorized_corpus` dependency) is correctly and consistently org-isolated. But:

- The five mutating functions downstream of discovery (`resolve_principal`, `resolve_relationship`, `activate_relationship`, `answer_question`, `approve_graph`) and one read endpoint (`get_principal_candidates`) gate solely on `Permission.AUTHORITY_REVIEW` — a coarse capability check that says nothing about *whose* data is being touched. This is the exact gap `SPECIFICATION/14_SECURITY_MODEL.md` §14.6 named and disclosed as still-open; this audit confirms it is **still true today**, verified against current code, not the doc's prose.
- `AuthorityRelationship.cross_org_approved` (`db/models.py:1102`, default `false`) — the column documented as the fail-closed opt-in for legitimate cross-org delegation — is **defined but never read anywhere in the codebase**. It is dead schema, not a working gate.
- **Concrete attack:** a caller holding ordinary `AUTHORITY_REVIEW` for Org A (a normal reviewer role) can `POST /v1/ai-authority-builder/corpora/{org_B_corpus_id}/approve` and receive Org B's full extracted principals, roles, reporting lines, relationships, conflicts, and gaps in the response, while writing a permanent, falsely-attributed approval record into Org B's own audit trail.
- **Azure Search + Blob Storage layer** (`authority_intelligence_service.py`): zero `organization_id` anywhere in the file — the Blob path (`authority-corpora/{corpus_id}/{document_id}-{filename}`) and the AI Search index schema (`id/corpus_id/document_id/filename/format/content/blob_path`) both key only on `corpus_id`. This is a real, live, already-self-documented gap (`AUTHORITY_INTELLIGENCE_PHASE2_VALIDATION_REPORT.md`: *"unsafe for multi-tenant rollout... exploitable the moment a second organization is onboarded"*) — and Milestone 2 is precisely that enablement.

### Evidence

**PASS for the router/service layer itself; BLOCKER for one specific endpoint.** `get_evidence`, `list_evidence`, and `verify_evidence`'s HTTP endpoint all correctly require `get_current_organization` and check `evidence.organization_id != organization_id` before returning anything. The hash chain itself is genuinely per-organization, not a filtered view of one global chain: `_previous_chain_hash`/`_resolve_chain_scope` (`intent_service.py`) and `verify_chain`'s own preceding-record lookup both filter strictly on `organization_id`, confirmed by direct read — a reorder or deletion in Org A's chain is undetectable from, and has zero effect on, Org B's chain.

**Confirmed BLOCKER (functional, not a leak):** `verify_chain` (`evidence_service.py:140`) calls `verify_evidence(db, record.id)`, omitting the required `organization_id` argument — guaranteed `TypeError`, confirmed by direct read, for any organization with ≥1 Evidence record. `GET /v1/evidence/chain/verify` — the one endpoint built specifically for credential-free third-party chain-integrity verification — does not work today except vacuously (an empty org "passes" because the loop body never executes).

**Confirmed BLOCKER, adjacent subsystem:** `GET /v1/agents/{id}` and `GET /v1/agents` (`agents.py`) have no `get_current_organization` and no `require_permission` dependency at all. `Agent` has no `organization_id` column of its own (only reachable via `Principal.organization_id`), and neither endpoint's underlying service functions (`agent_service.get_agent`, `list_certificates`, `list_audit_events`, `intent_service.list_decisions_for_agent`/`list_evidence_for_agent`) filter by it. Any caller can enumerate every tenant's agents and read another tenant's decision history, evidence summaries, and audit events through this one page's backend — the same Evidence data the dedicated Evidence router correctly protects is fully exposed one hop away.

### Authority Graph

Covered above under Authority Intelligence — the two are the same subsystem in this codebase (the "Authority Graph" the brief asks about is the AI Authority Builder's 8 extraction categories plus the real Authority Model). No separate findings beyond what's listed there.

### SDK

**WARNING, not the BLOCKER the milestone summary's own disclosure implied.** Of every SDK HTTP call (`register`, `activate`, `rotate_keys`, `retire`, `heartbeat`, `authorize`, `get_decision`, `health`, `version`), exactly **one** — the operator-keyed `POST /v1/principals` fallback inside `_resolve_principal_id` — is actually gated by `get_current_organization` and will newly fail (`400 organization_id_required_for_operator_key`) because of Milestone 2. In practice, `register()` is already broken today for an unrelated, pre-existing, Milestone-1-era reason: the preceding `GET /v1/principals` call sends **no credentials at all** and 401s first (`require_permission(AGENT_VIEW)` was added in Milestone 1's `c9b1809`), so the Milestone 2 break is masked, not primary. Every other SDK method hits endpoints with no organization dependency and is unaffected.

`scripts/smoke_test.py` genuinely does fail at its `create_principal()` step because of Milestone 2 (no org header sent) — this is a real, confirmed BLOCKER for the smoke test as written, and it would independently fail again two steps later at `verify_evidence()` for an unrelated pre-existing bug (missing auth headers in the script itself).

The frontend's Operator Key path (`apiClient.ts`, `OperatorKeyField.tsx`) never sends `X-PayReality-Organization-Id` anywhere — confirmed by a full grep of `src/app/live`. Any user with an Operator Key configured (the documented "no human login yet" fallback path, still real and supported per `operatorKey.ts`'s own comment) will get `400` on Principals, Evidence, all of Runtime Policies, Organisation Settings, Users, and API Keys — everything gated by `get_current_organization`.

No SDK/transport-layer assumption blocks Azure deployment — `base_url` is a plain overridable string, retries are generic 5xx/network-based, nothing hardcodes topology.

### Background Jobs

**PASS.** The only two candidates found in a full-tree grep — `_reconcile_opa_with_active_policies` (startup hook, `main.py`) and `process_due_schedules` (manually/externally triggered, no task runner exists anywhere in this platform) — are both, by design, platform-wide operations that correctly thread each organization's or each schedule's own `organization_id` internally. `process_due_schedules`'s function body is correct; its router's *authorization gate* is the confirmed bug already named above under Runtime Policies — a distinct issue from "is the job itself tenant-aware," which it is.

### Caching

**PASS, confirmed negative.** A full-tree grep for `lru_cache`, module-level `_cache`/`{}`/`dict()`/`set()`, and any client instantiated once at import time found exactly one hit: `security.py`'s `_request_log`, an in-process rate-limiter keyed by client IP. It holds only timestamps, never response data or tenant-identifying content — not a cross-tenant leak. Two real caveats, both WARNING-level and about correctness-under-scale, not isolation: (1) being per-process, Azure Container Apps' default 3-replica autoscale means the advertised "120 req/min" limit is actually `120 × replica_count`, inconsistent depending which replica a client lands on; (2) it's keyed by IP only, so two tenants sharing an egress IP/NAT could throttle each other. No compiled bundle, `PolicyDiff`, or `SafetyCheckResult` is cached/memoized anywhere — confirmed by direct read of `HttpOpaClient` and the relevant service modules, not assumed from the architecture's claim.

### Configuration

**PASS.** Every setting in `config.py` is either genuinely platform-wide infrastructure config (correctly so — `database_url`, `opa_url`, `admin_api_key`, signing keys, Azure endpoints) or one-time bootstrap identity used only by the no-op-after-first-use owner-bootstrap hook. The one setting the brief specifically worried about, `session_timeout_minutes`, was independently confirmed to be read per-organization at the point of use (`auth_service.py`: `organization.settings.get("session_timeout_minutes", DEFAULT)`), with the global value acting only as a fallback default, not an override.

**Confirmed BLOCKER, startup/lifecycle:** `main.py`'s startup hook unconditionally calls `ensure_owner_bootstrapped`, which resolves "the organisation" via `order_by(Organization.created_at).limit(1)` — the same "whichever org was created first" pattern Milestone 2's own `dependencies.py` docstring calls out as wrong for the Operator Key, still present here unchanged. It is non-destructive for a second org (returns early if that org already has an Owner) — but the actual problem is upstream of that: **there is no code path anywhere in this application that constructs a second `Organization` row.** `POST /v1/auth/setup-owner` only updates an existing Owner for whatever org already resolves; nothing creates a new organization. Milestone 2 built per-organization isolation; nothing in this codebase can bring a second organization into existence to test that isolation against in production.

---

## Phase 3 — Azure Readiness

| # | Area | Verdict | Evidence |
|---|---|---|---|
| 1 | Postgres | **PASS** | Migration `a7d3e9f2c6b1` uses only nullable `add_column`/`create_foreign_key`/`create_index`/a partial unique index/a plain backfill `UPDATE` — no extensions, no version-gated SQL. Azure side is Postgres Flexible Server v16 (`terraform/modules/postgres/main.tf`); nothing incompatible. |
| 2 | Container Apps | **WARNING** | OPA is embedded per-replica (unchanged topology); each replica independently reconciles every organization's package at boot. Correct at today's scale; per-replica memory/cold-start time grows linearly with total org+policy count as tenants are added — a scaling ceiling, not a correctness bug. |
| 3 | Key Vault | **PASS** | `admin_api_key`/`evidence_signing_key_*`/`anthropic_api_key` are plain env-var fields already mapped by Terraform's `secret { key_vault_secret_id }` blocks; Milestone 2 added no new secrets. |
| 4 | Blob Storage | **WARNING (live risk)** | Real, shipped code (`authority_intelligence_service.py`), no `organization_id` in the storage path — see Authority Intelligence above. |
| 5 | AI Search | **WARNING, leans BLOCKER for multi-tenant rollout** | Real, shipped code, no `organization_id` field in the index schema or query filter — already self-documented as unsafe for multi-tenancy in a prior validation report; Milestone 2 is exactly the enablement that makes this exploitable. |
| 6 | AI Foundry | **PASS (mechanics) / WARNING (stale status reporting)** | Uses `DefaultAzureCredential` correctly, live on staging only. `organization_service.get_integrations_status` still hardcodes `"azure_openai": "configuration_required"` even though a real integration now exists — a stale status, not a security issue. |
| 7 | Managed Identity | **PASS** | All new Azure clients (Blob, Search, AI Foundry) use `DefaultAzureCredential` exclusively; Container App's user-assigned identity confirmed live-necessary by a real prior incident. |
| 8 | Monitoring | **PASS** | Application Insights wired unconditionally into `main.py`'s app creation via `observability.py`; live-verified telemetry flow already documented. Untouched by Milestone 2. |
| 9 | Backups / DR | **PASS** | Geo-redundant Postgres backups, 35-day retention, already live in prod config. Milestone 2's columns are nullable/additive in the same shared schema — a standard `pg_dump`/`pg_restore` boundary still captures every organization uniformly; no new per-org backup story is needed because this is row-level, not physically isolated, multi-tenancy. |
| 10 | Networking | **PASS** | Single VNet, private endpoints, no public path to Key Vault/Storage/Postgres — consistent with row-level multi-tenancy; Milestone 2 requires no networking change. |

**One cross-cutting BLOCKER found outside the original 10-item list, worth flagging with equal weight:** `terraform/main.tf`'s AI Foundry and AI Search modules are **unconditional** — no per-environment toggle. Production was deliberately bootstrapped *without* them, but that exclusion exists only as a human decision, not as Terraform state. The next `terraform apply -var-file=prod.tfvars`, run without careful diffing, will silently propose creating both services in production — bundled with whatever app-image and DB-migration changes haven't yet been applied either, since production's deployed image predates both Authority Intelligence and Milestone 2 entirely.

---

## Phase 4 — Migration Readiness

1. **Database migration**: `a7d3e9f2c6b1` is safe before or after a hypothetical Render→Azure cutover — purely additive, idempotent-guarded backfill. No Milestone-2-specific ordering constraint beyond the already-documented generic one (copied dataset's `alembic_version` must match this linear history before `upgrade head`).
2. **Tenant data**: not yet a real scenario. Confirmed by grep: exactly one organization exists, and (per Phase 2's Configuration finding) there is no way to create a second through the running application. "Tenant data migration" presupposes a second tenant that cannot currently come into existence.
3. **OPA bundles**: `reconcile_opa_with_active_policies` is confirmed wired unconditionally into `main.py`'s startup hook and correctly iterates every organization's active set — a fresh Azure deployment, cold start, or region migration will correctly repopulate every per-org OPA package.
4. **Evidence**: no Azure-specific concern in the signing/chaining mechanism itself (org-scoped chaining predates Milestone 2). The one real, already-documented risk is generic to any Render→Azure data *copy*: the signing-key registry must have Render's actual public key registered before/during a copy, or verification fails on the first migrated record.
5. **Rollback**: a real, specified, DNS/config-level rollback plan exists (`PRODUCTION_BOOTSTRAP/08_ROLLBACK_PLAN.md`) but is unexecuted and has no database-level component, because Render remains the live production system throughout Azure's bootstrap to date. Milestone 2 doesn't change this, since no real tenant data yet exists to roll back.

---

## Phase 5 — Risk Assessment

| Area | Status | Risk | Required Action |
|---|---|---|---|
| Runtime Policy CRUD/compile/deploy org-scoping | **PASS** | None found beyond narrow, currently-unreachable defense-in-depth gaps | Opportunistic: add explicit `organization_id` filters to `diff_versions`'s affected-agents query, `resolve_mandate_ids`/`resolve_enterprise_system`, `effective_status`'s sibling lookup |
| `process_due_schedules` authorization gate | **BLOCKER** | Any tenant's own Owner/Governance Admin can trigger execution of every other tenant's due schedules | Gate this endpoint behind platform-admin-only auth (Operator Key + explicit org, or a new platform-admin permission), not the per-tenant `RUNTIME_POLICY_PUBLISH` permission. Small, scoped fix. |
| OPA package/bundle isolation | **PASS** | None found | None |
| Authority Builder mutating endpoints (`resolve_principal`, `resolve_relationship`, `activate_relationship`, `answer_question`, `approve_graph`) | **BLOCKER** | Cross-tenant read/write/forged-audit-record via a coarse permission-only gate | Add organization ownership verification (via corpus or Principal's own `organization_id`) to all five before any second tenant exists |
| `get_principal_candidates` | **BLOCKER** | No auth dependency at all | Add the same organization check as its sibling reads |
| `cross_org_approved` dead schema | **WARNING** | Documented fail-closed gate doesn't actually gate anything, because there's nothing to gate yet | Wire it in once the BLOCKER above is fixed, or remove the column if the feature is abandoned |
| AI Policy Builder single-document pipeline | **BLOCKER** | Fully unauthenticated, unscoped reads of extracted governance/DoA document content; promotion inherits the caller's org with no verification of the uploading org | Add `organization_id` to `PolicyExtractionUpload`/`PolicyExtractionCandidate`, auth-gate all five read endpoints, extend the promotion guard to this path |
| Evidence chain verification (`verify_chain`) | **BLOCKER** | Public integrity-verification endpoint crashes for any populated organization | One-line fix: pass `organization_id` into the internal `verify_evidence` call. Add test coverage — currently zero. |
| Agent Detail Page backend (`GET /v1/agents`, `GET /v1/agents/{id}`) | **BLOCKER** | Fully unauthenticated cross-tenant read of agents, decisions, evidence summaries, audit events | Add `get_current_organization` + an organization check against the resolved agent's Principal |
| Organization onboarding | **BLOCKER (for real multi-tenancy, not for Azure infra)** | No second tenant can be created through the app at all | Build a genuine organization-creation path before treating this platform as multi-tenant in production, not just multi-tenant-shaped in schema |
| Azure Blob Storage / AI Search org-scoping | **BLOCKER (already self-documented)** | Authority Intelligence documents/vectors are fully cross-tenant-readable the moment a second org exists | Add `organization_id` to both the Blob path and the Search index schema/query filter before any second tenant's documents are ever uploaded |
| Terraform unconditional AI Foundry/AI Search modules | **WARNING** | A careless `terraform apply -var-file=prod.tfvars` silently creates both services in production | Add an explicit per-environment toggle variable before the next production apply |
| Rate limiting under horizontal scale | **WARNING** | Per-replica, IP-keyed — inconsistent effective limits, cross-tenant IP-sharing throttling | Move to a shared store (Redis/Postgres-backed) before relying on it at real multi-tenant, multi-replica scale |
| SDK / frontend / smoke_test Operator Key gap | **WARNING (already disclosed, scoped correctly)** | Operator-key-authenticated calls to org-scoped endpoints now fail; frontend's Operator Key fallback path is fully broken for those endpoints | Already tracked as Milestone 6 (SDK & Integration Modernization) follow-up per the roadmap; no new action needed beyond what's already planned |
| Postgres / Container Apps / Key Vault / Managed Identity / Monitoring / Backups-DR / Networking | **PASS** (Container Apps: WARNING on scaling ceiling) | None blocking | None required before Milestone 3 |

---

## Phase 6 — Final Verdict

**1. Is the platform now genuinely multi-tenant?**
Partially. The Runtime Policy / OPA / Decision Engine core — Milestone 2's actual scope — is genuinely, verifiably multi-tenant. The platform as a whole is not: Authority Intelligence's mutating endpoints, the single-document Policy Builder pipeline, and the Agent Detail Page all have zero or coarse-only organization enforcement, and there is no way to onboard a second tenant through the application at all.

**2. Is there any remaining platform-global state?**
One piece, and it's benign for isolation purposes: the in-process rate-limiter (`_request_log`) is per-process, IP-keyed, shared across whatever tenants happen to share a process/replica — a scaling-correctness issue, not a data leak. No compiled bundle, policy diff, or safety-check result is cached or shared across requests; confirmed by direct code read, not assumed.

**3. Can one tenant ever influence another tenant?**
Yes, today, in five confirmed ways: (a) trigger execution of another tenant's scheduled policy activations/retirements via `process_due_schedules`; (b) read, and in `activate_relationship`'s case write into, another tenant's Authority Graph via the five unguarded mutating endpoints; (c) read another tenant's uploaded governance-document extraction candidates, and have their own promotion land that content into their own org's live policy set with no verification of provenance; (d) read another tenant's agents/decisions/evidence via the Agent Detail Page's backend; (e) once Blob Storage/AI Search are used for a second tenant, read that tenant's uploaded documents outright.

**4. Is Runtime Authority enterprise-safe?**
The Decision Engine, Runtime Policy compilation/activation/storage/versioning/lifecycle, and OPA evaluation — the actual live-traffic enforcement path — is enterprise-safe as verified. The one confirmed gap in this specific area (`process_due_schedules`'s authorization gate) is narrow and easily fixed. Runtime Authority in the strict sense: **yes, with one small fix pending.**

**5. Is Authority Intelligence enterprise-safe?**
No. This is the single largest gap found in this audit — five unguarded mutating endpoints, a dead fail-closed column, an entirely unscoped parallel pipeline (AI Policy Builder single-document), and an already-self-documented Blob/Search org-scoping gap. None of this was in Milestone 2's stated scope, but it is squarely what "genuinely multi-tenant" has to mean before a second real tenant's data touches this system.

**6. Is Azure migration now primarily an infrastructure exercise rather than an architectural exercise?**
For the ten named Azure service areas, yes — nothing found blocks Postgres, Container Apps, Key Vault, Managed Identity, Monitoring, Backups/DR, or Networking, and Milestone 2 introduced no new Azure-specific complexity. But two already-live Azure integrations (Blob Storage, AI Search) carry an architectural gap, not an infrastructure one, and the Terraform-level production-apply risk is also architectural (a missing environment toggle), not infrastructural.

**7. Would you approve beginning Milestone 3?**

**Conditional — not a bare yes.**

Specifically:
- The **Azure infrastructure workstream** (the ten named service areas) has no blocker from Milestone 2 and can proceed.
- **Do not** consider Milestone 2 / the "multi-tenant hardening" line of work complete, and **do not** onboard a real second tenant, until the five confirmed BLOCKERs above (`process_due_schedules` gate, the five Authority Builder mutating endpoints, the AI Policy Builder pipeline, `verify_chain`'s crash, and the Agent Detail Page) are remediated. None of them require redesigning anything Milestone 2 built — they are scoped, additive authorization/organization checks, matching the exact pattern Milestones 1 and 2 already established repeatedly.
- The **Blob Storage / AI Search org-scoping gap** should be treated as gating specifically because it sits inside Milestone 3's own remit (Azure AI Search / AI Foundry) — fix it as part of, or immediately before, any production use of those two services, not deferred to a later milestone.
- The **Terraform unconditional-module risk** should be fixed immediately, independent of any milestone sequencing, since it's a live footgun on the very next `terraform apply`.

If the user wants to proceed into Milestone 3's pure-infrastructure work in parallel with a short, scoped remediation pass on the BLOCKERs above, that's architecturally sound. Proceeding into Milestone 3 as if Milestone 2 fully delivered "genuine multi-tenancy" — without that remediation — is not recommended.

---

## Recommendation

1. **Immediate, small, scoped fixes** (does not require re-opening Milestone 2's design, matches its own established remediation pattern): `process_due_schedules`'s authorization gate; `verify_chain`'s missing argument; the Agent Detail Page's missing auth/org check; the Terraform environment toggle for AI Foundry/AI Search.
2. **A short, dedicated remediation milestone** (call it Milestone 2b, or fold into the top of Milestone 3's own punch list) for: the five Authority Builder mutating endpoints, `cross_org_approved` actually being wired in (or removed), the AI Policy Builder single-document pipeline's org-scoping, and Blob Storage/AI Search org-scoping.
3. **A real organization-onboarding path** — this doesn't need to be built before Milestone 3's infrastructure work, but should exist before any claim of "the platform supports multiple tenants" is made externally (pitch deck, sales conversation, enterprise pilot).
4. **Proceed with Milestone 3's Azure infrastructure workstream** on its own merits — nothing found here blocks it, and it is largely independent of the application-layer gaps above.

Not proceeding to implement any of the above without the user's go-ahead, per this verification's own Scope Rules.
