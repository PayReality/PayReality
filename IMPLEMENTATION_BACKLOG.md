# Implementation Backlog

Every item is written to be pasted directly into a GitHub Issue. IDs are stable references (`BL-<phase>.<n>`) — use them in commit messages and PR titles so history stays traceable back to this backlog. "Files affected" names the primary files; secondary/test files are implied by "Testing strategy" and not separately enumerated unless non-obvious.

---

## Phase 0 — Legacy Removal & Stabilisation

### BL-0.1: Backfill tooling — legacy Authority/Mandate → RuntimePolicy draft
- **Priority**: Critical
- **Complexity**: Medium
- **Dependencies**: None
- **Duration**: 3–5 days
- **Risk**: Medium — incorrect translation would produce a wrong draft, though nothing auto-activates
- **Files affected**: new `services/legacy_backfill_service.py`; reads `db/models.py::Authority`/`Mandate`; writes `RuntimePolicyRecord` via existing `runtime_policy_service.create_policy`
- **Migration considerations**: Operator-triggered only, never automatic; run against a non-production copy first
- **Testing strategy**: Unit tests translating known Authority/Mandate fixtures into expected `RuntimePolicy` shapes; a golden-file comparison against manually-verified expected output
- **Acceptance criteria**: Every currently-`active` legacy Policy/Mandate produces exactly one `RuntimePolicy` draft with an equivalent amount/currency condition; no draft is auto-approved

### BL-0.2: Cutover verification harness
- **Priority**: Critical
- **Complexity**: Medium
- **Dependencies**: BL-0.1
- **Duration**: 3–4 days
- **Risk**: Low — read-only, dry-run only
- **Files affected**: new script using `runtime_policy_service.dry_run_policy` and the legacy `policy_service`'s equivalent read path against a shared sample of historical Intents
- **Migration considerations**: None (no writes)
- **Testing strategy**: Run against a fixed historical-Intent fixture set with known expected outcomes
- **Acceptance criteria**: For every backfilled policy, dry-run outcome matches the legacy pipeline's actual historical decision for the same Intent, across the full comparison sample

### BL-0.3: Disable legacy authoring endpoints
- **Priority**: Critical
- **Complexity**: Small
- **Dependencies**: BL-0.1, BL-0.2 (every backfilled policy verified and deployed first)
- **Duration**: 1 day
- **Risk**: Medium — could surface an unknown caller dependency
- **Files affected**: `routers/policies.py` (authoring endpoints only — compile/activate/document-upload)
- **Migration considerations**: Return `410 Gone` with a clear message, not a silent no-op; add monitoring/alerting on any hit
- **Testing strategy**: Update existing router tests to assert `410`; add an alert-fires test if the monitoring stack supports it
- **Acceptance criteria**: Legacy authoring endpoints return `410`; read-only historical endpoints unaffected; one full stabilisation window with zero unexpected caller alerts

### BL-0.4: Defense-in-depth writer assertion
- **Priority**: High
- **Complexity**: Small
- **Dependencies**: None (can land before BL-0.3)
- **Duration**: 1 day
- **Risk**: Low
- **Files affected**: `services/runtime_policy_service.py::deploy_policy`
- **Migration considerations**: None — additive check only
- **Testing strategy**: Unit test asserting `deploy_policy` raises if the previously-active `Policy.bundle_uri` doesn't match the expected `runtime_policy_studio:...` format
- **Acceptance criteria**: Any write to the active-policy slot not originating from `runtime_policy_service` is detected and rejected, not silently overwritten

### BL-0.5: Dead-column decision and migration
- **Priority**: Medium
- **Complexity**: Small
- **Dependencies**: A production data check confirming zero non-null historical values
- **Duration**: 1–2 days
- **Risk**: Low if the data check confirms zero usage; treat as blocked otherwise
- **Files affected**: `db/models.py::Intent`, a new Alembic (or equivalent) migration
- **Migration considerations**: Independent migration, not bundled with BL-0.1–0.4; must include a working down-migration
- **Testing strategy**: Migration up/down round-trip test
- **Acceptance criteria**: `requested_scope`/`metadata` columns either removed (with confirmed-zero-usage evidence) or explicitly documented as reserved — decision recorded, not left ambiguous

---

## Phase 1 — Authority Model

### BL-1.1: Organisation FK on Principal
- **Priority**: High | **Complexity**: Small | **Dependencies**: Phase 0 complete | **Duration**: 1 day
- **Risk**: Low — nullable, additive
- **Files affected**: `db/models.py::Principal`, migration
- **Testing strategy**: Schema migration test; existing `Principal`-dependent tests unmodified and passing
- **Acceptance criteria**: Column exists, nullable, FK-enforced; zero behavior change to existing matching path

### BL-1.2: BusinessUnit, Department, Team tables
- **Priority**: High | **Complexity**: Small | **Dependencies**: BL-1.1 | **Duration**: 2 days
- **Risk**: Low
- **Files affected**: `db/models.py` (three new classes), migration, minimal CRUD in `services/`
- **Testing strategy**: Unit tests for CRUD; FK integrity tests (department requires business unit, etc.)
- **Acceptance criteria**: Three-level hierarchy creatable and queryable; each level independently optional per Principal
- **Status: Done in two parts.** The tables/migration shipped in Phase 1 as planned; the "minimal CRUD" half of this item did not ship then and had no HTTP surface at all until Phase 5 Release 1 (`GET/POST/PATCH/DELETE /v1/business-units`, `/v1/departments`, `/v1/teams`, plus an Organisation Settings UI) closed that specific gap.

### BL-1.3: Principal role/org/BU/department/team columns
- **Priority**: High | **Complexity**: Small | **Dependencies**: BL-1.1, BL-1.2 | **Duration**: 1 day
- **Risk**: Low — all nullable
- **Files affected**: `db/models.py::Principal`, migration
- **Testing strategy**: Existing Principal tests pass unmodified; new tests for the additive columns only
- **Acceptance criteria**: All five new columns present and nullable; zero impact on `RuntimePolicy.scope.principal` matching

### BL-1.4: Resource table
- **Priority**: Medium | **Complexity**: Small | **Dependencies**: BL-1.1 | **Duration**: 2 days
- **Risk**: Low
- **Files affected**: `db/models.py::Resource` (new), migration, `services/resource_service.py` (new, minimal CRUD)
- **Testing strategy**: CRUD unit tests; a test confirming `Scope.resource` string-matching is unaffected by this table's existence
- **Acceptance criteria**: Resource creatable, optionally owned by a Principal; `RuntimePolicy` unaffected until explicitly wired (BL-2.4)

### BL-1.5: AuthorityRelationship extension
- **Priority**: Critical | **Complexity**: Medium | **Dependencies**: BL-1.1, BL-1.3, BL-1.4 | **Duration**: 3–4 days
- **Risk**: Medium — this table is read by the existing Authority Builder UI; must not break existing display
- **Files affected**: `db/models.py::AuthorityRelationship`, migration, `services/ai_authority_builder_service.py` (ensure existing writes still populate the text columns unchanged)
- **Migration considerations**: All new columns additive/nullable; `status` defaults to `'proposed'` for new rows, backfilled to `'active'` for existing historical rows only after manual review (do not assume historical extracted relationships are automatically "active")
- **Testing strategy**: Existing Authority Builder tests pass unmodified; new tests for FK resolution, validity-window filtering, revocation status transitions
- **Acceptance criteria**: New FK/time/status columns present; existing `CorpusReviewPage.tsx` rendering unaffected; a relationship can be created with real FK endpoints

### BL-1.6: Cross-org explicit approval flag
- **Priority**: Medium | **Complexity**: Small | **Dependencies**: BL-1.5 | **Duration**: 1 day
- **Risk**: Low
- **Files affected**: `db/models.py::AuthorityRelationship` (`cross_org_approved` column)
- **Testing strategy**: Unit test confirming a cross-org edge without the flag is excluded from traversal (BL-4.3/4.4)
- **Acceptance criteria**: Cross-organisation delegation edges are inert by default; require explicit approval to participate in traversal

---

## Phase 2 — Runtime Authority Context

### BL-2.1: `resolve_runtime_authority_context` function
- **Priority**: High | **Complexity**: Medium | **Dependencies**: Phase 1 complete | **Duration**: 3 days
- **Risk**: Low — purely additive read function
- **Files affected**: new `services/authority_context_service.py`
- **Testing strategy**: Unit tests per resolved field (org, department, direct delegation lookup, risk, resource)
- **Acceptance criteria**: Given an Agent/Intent, returns a fully populated context object matching `PHASE_2_RUNTIME_CONTEXT.md`'s field table

### BL-2.2: Wire context into `submit_intent`
- **Priority**: High | **Complexity**: Small | **Dependencies**: BL-2.1 | **Duration**: 1–2 days
- **Risk**: Medium — touches the live decision hot path; must be additive only
- **Files affected**: `services/intent_service.py::submit_intent`
- **Migration considerations**: Merge new context under a clearly namespaced key (`context.authority.*`); never overwrite caller-supplied `Intent.context` keys
- **Testing strategy**: Full existing `intent_service`/decision-engine integration test suite must pass unmodified; new tests asserting the enriched context reaches `build_opa_input` correctly and existing decisions for policies with no context-dependent conditions are byte-identical to before
- **Acceptance criteria**: Zero change in outcome for any policy not explicitly authored to reference the new context fields

### BL-2.3: Policy Studio UI support for `context.authority.*` conditions
- **Priority**: Medium | **Complexity**: Small | **Dependencies**: BL-2.2 | **Duration**: 2 days
- **Files affected**: `src/app/policy-studio/components/ConditionRow.tsx`, `ScopeFields.tsx`
- **Testing strategy**: Frontend component tests; manual verification a condition on `context.authority.department` saves and compiles correctly
- **Acceptance criteria**: An author can select a department/org/risk condition from the UI without hand-typing the field path

### BL-2.4: Resource-ID resolution in context (optional path)
- **Priority**: Low | **Complexity**: Small | **Dependencies**: BL-1.4, BL-2.1 | **Duration**: 1 day
- **Risk**: Low
- **Files affected**: `services/authority_context_service.py`
- **Testing strategy**: Unit test for resource resolution when an Intent names a resource identifier
- **Acceptance criteria**: When present, resolved `Resource.type`/`owner_principal_id` available in context; absent otherwise, no error

---

## Phase 3 — Runtime Authority Language (RTAL)

### BL-3.1: Formal grammar specification and test corpus
- **Priority**: High | **Complexity**: Medium | **Dependencies**: Phase 1 schema stable | **Duration**: 1 week
- **Files affected**: new `docs/RTAL_GRAMMAR.md`, new `tests/fixtures/rtal/*.rtal`
- **Testing strategy**: A corpus of valid and deliberately invalid `.rtal` files, each with an expected parse result or expected error
- **Acceptance criteria**: Grammar unambiguously covers every example in `PHASE_3_DSL.md`

### BL-3.2: Lexer and parser
- **Priority**: High | **Complexity**: Large | **Dependencies**: BL-3.1 | **Duration**: 2–3 weeks
- **Files affected**: new `domain/rtal/lexer.py`, `domain/rtal/parser.py`
- **Testing strategy**: Full corpus from BL-3.1 parses to the expected AST or the expected structured error, never a raw exception
- **Acceptance criteria**: Round-trip: parse → re-serialize → parse again produces an identical AST

### BL-3.3: RTAL → RuntimePolicy compiler
- **Priority**: High | **Complexity**: Medium | **Dependencies**: BL-3.2 | **Duration**: 1 week
- **Files affected**: new `domain/rtal/compiler.py`
- **Migration considerations**: Must produce `RuntimePolicy` objects indistinguishable from any other authoring surface's output
- **Testing strategy**: For each RTAL example, assert the compiled `RuntimePolicy` matches an equivalent hand-constructed one field-by-field; feed the result through the existing `compile_bundle()` and assert identical Rego to a UI-authored equivalent
- **Acceptance criteria**: A `.rtal` file compiles, dry-runs, and deploys through the existing pipeline with zero compiler/OPA changes

### BL-3.4: Delegation-reference validation
- **Priority**: Medium | **Complexity**: Small | **Dependencies**: BL-3.3, Phase 1 (BL-1.5) | **Duration**: 2–3 days
- **Files affected**: `domain/rtal/compiler.py`
- **Testing strategy**: A `delegated_from` clause referencing a non-existent or expired/revoked delegation fails compilation with a structured error
- **Acceptance criteria**: No RTAL-authored policy can silently assume a delegation that doesn't actually exist

### BL-3.5: Editor tooling (syntax highlighting/lint)
- **Priority**: Low | **Complexity**: Small | **Dependencies**: BL-3.1 | **Duration**: 2–3 days
- **Files affected**: a TextMate/LSP grammar file for the team's existing editor tooling
- **Testing strategy**: Manual verification in the team's actual editor
- **Acceptance criteria**: Basic syntax highlighting for `.rtal` files; not a full language server in this iteration

---

## Phase 4 — Authority Graph

### BL-4.1: `source_authority_relationship_id` on RuntimePolicyRecord
- **Priority**: High | **Complexity**: Small | **Dependencies**: Phase 1 | **Duration**: 1 day
- **Files affected**: `db/models.py::RuntimePolicyRecord`, migration
- **Testing strategy**: Migration test; existing policy creation tests unaffected
- **Acceptance criteria**: Nullable FK present; existing rows unaffected

### BL-4.2: Promotion mechanism generalization
- **Priority**: High | **Complexity**: Medium | **Dependencies**: BL-4.1 | **Duration**: 1 week
- **Files affected**: `services/ai_policy_builder_service.py` (generalize `promote_candidate`'s pattern), new `services/authority_promotion_service.py`
- **Migration considerations**: Reuses, does not duplicate, the existing candidate-promotion review-lifecycle discipline
- **Testing strategy**: A test promoting an `AuthorityRelationship` produces a draft indistinguishable in review-lifecycle behavior from a candidate-promoted policy
- **Acceptance criteria**: Promotion never auto-activates; conflicting promotions correctly fail via existing `scope_overlap.py` logic

### BL-4.3: Downstream traversal query
- **Priority**: Medium | **Complexity**: Medium | **Dependencies**: Phase 1 (BL-1.5, BL-1.6) | **Duration**: 3–4 days
- **Files affected**: new `services/authority_graph_service.py`
- **Testing strategy**: Fixture-based tests for chains of depth 1, 3, and at the max-depth boundary; a revoked/expired/cross-org-unapproved edge is correctly excluded
- **Acceptance criteria**: Matches `PHASE_4_AUTHORITY_GRAPH.md`'s traversal definition exactly

### BL-4.4: Upstream traversal query
- **Priority**: Medium | **Complexity**: Small | **Dependencies**: BL-4.3 (shares most logic) | **Duration**: 1–2 days
- **Testing strategy**: Mirror of BL-4.3's fixtures, reversed direction
- **Acceptance criteria**: Symmetric correctness with BL-4.3

### BL-4.5: Impact analysis query
- **Priority**: Medium | **Complexity**: Medium | **Dependencies**: BL-4.1, BL-4.4 | **Duration**: 3–4 days
- **Files affected**: `services/authority_graph_service.py`
- **Testing strategy**: A test revoking a delegation with two downstream promoted policies correctly surfaces both before the revocation is confirmed
- **Acceptance criteria**: Returns a concrete, accurate list of affected `RuntimePolicyRecord` rows for any given relationship/principal

### BL-4.6: API endpoints for the five example queries
- **Priority**: Low | **Complexity**: Small | **Dependencies**: BL-4.3–4.5 | **Duration**: 2–3 days
- **Files affected**: new `routers/authority_graph.py`
- **Testing strategy**: One integration test per example query in `PHASE_4_AUTHORITY_GRAPH.md`
- **Acceptance criteria**: Each of the five named example queries answerable via a documented endpoint

---

## Phase 5 — Evidence Engine

### BL-5.1: `previous_hash`/`payload_version` fields
- **Priority**: High | **Complexity**: Small | **Dependencies**: None | **Duration**: 1–2 days
- **Files affected**: `domain/evidence/signing.py`, `services/intent_service.py::_build_evidence_payload`
- **Migration considerations**: Additive only; existing (v1) records unaffected and remain verifiable exactly as today
- **Testing strategy**: Existing Evidence signing/verification tests pass unmodified; new tests for v2 payload shape
- **Acceptance criteria**: New records carry both fields; old records verify identically to today

### BL-5.2: Chaining write path
- **Priority**: High | **Complexity**: Medium | **Dependencies**: BL-5.1 | **Duration**: 1 week
- **Files affected**: `services/intent_service.py::append_evidence`
- **Migration considerations**: Chain scoped per-Organisation (requires Principal's `organization_id` — Phase 1 — falls back to un-chained if absent, logged, never silently wrong)
- **Testing strategy**: A test asserting three sequential Evidence records for one Organisation correctly link; a test asserting two different Organisations' chains never cross
- **Acceptance criteria**: Every new Evidence record's `previous_hash` correctly references its Organisation-scoped predecessor

### BL-5.3: Chain verification tool/endpoint
- **Priority**: High | **Complexity**: Medium | **Dependencies**: BL-5.2 | **Duration**: 1 week
- **Files affected**: `services/evidence_service.py`, `routers/evidence.py`
- **Testing strategy**: A test that deletes a record from a test chain and confirms verification detects the gap; a test confirming a fully intact chain verifies clean
- **Acceptance criteria**: Detects both signature tampering (existing) and chain gaps (new) with distinct, clear error reporting

### BL-5.4: Lineage query (Decision → Policy → Authority → Document)
- **Priority**: Medium | **Complexity**: Medium | **Dependencies**: BL-4.1, BL-4.2 | **Duration**: 1 week
- **Files affected**: new `services/evidence_lineage_service.py`
- **Testing strategy**: A fixture chain covering all five hops; a fixture with no Authority Model provenance correctly stops at the Policy level
- **Acceptance criteria**: Full trace resolves for a promotion-sourced policy; graceful partial trace for a hand-authored one

### BL-5.5: Archival export job
- **Priority**: Low | **Complexity**: Medium | **Dependencies**: BL-5.2 | **Duration**: 1–2 weeks (includes WORM-provider selection)
- **Files affected**: new operational tooling, outside the application codebase proper
- **Testing strategy**: A restore-and-verify drill against the exported archive
- **Acceptance criteria**: A scheduled export produces a chain-verifiable, durable copy independent of the live database

---

## Phase 6 — Platform Capabilities (sequence each independently against real demand)

### BL-6.1: Policy Simulation batch API
- **Priority**: Medium | **Complexity**: Medium | **Dependencies**: None (extends existing `dry_run.py`) | **Duration**: 1–2 weeks
- **Acceptance criteria**: A set of hypothetical policy changes evaluated against a batch of sample Intents, with zero live-traffic impact, reusing `dry_run.py`'s proven isolation mechanism

### BL-6.2: Replay Engine
- **Priority**: Medium | **Complexity**: Medium | **Dependencies**: Historical bundle versions retained | **Duration**: 2 weeks

### BL-6.3: Runtime Analytics aggregation
- **Priority**: Low | **Complexity**: Small | **Dependencies**: None | **Duration**: 1 week

### BL-6.4: Authority Explorer UI
- **Priority**: Low | **Complexity**: Medium | **Dependencies**: BL-4.3, BL-4.4 | **Duration**: 2–3 weeks

### BL-6.5: Governance Explorer UI
- **Priority**: Low | **Complexity**: Medium | **Dependencies**: BL-5.4 | **Duration**: 2 weeks

### BL-6.6: Policy Diff across an impacted set
- **Priority**: Low | **Complexity**: Small | **Dependencies**: BL-4.5, existing `VersionsPage.tsx` diff | **Duration**: 3–5 days

### BL-6.7: Risk Heatmap UI
- **Priority**: Low | **Complexity**: Small | **Dependencies**: BL-6.3 | **Duration**: 1 week

### BL-6.8: AI Explainability narrative renderer
- **Priority**: Low | **Complexity**: Small | **Dependencies**: BL-5.4 | **Duration**: 1 week

### BL-6.9: Enterprise Search index
- **Priority**: Low | **Complexity**: Medium | **Dependencies**: None | **Duration**: 2–3 weeks

### BL-6.10: Delegation Explorer UI
- **Priority**: Low | **Complexity**: Small | **Dependencies**: BL-4.3, BL-4.4 | **Duration**: 1–2 weeks

### BL-6.11: Decision Replay / Historical Reconstruction UI
- **Priority**: Low | **Complexity**: Medium | **Dependencies**: BL-5.3, BL-5.4 | **Duration**: 2–3 weeks
