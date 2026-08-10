# Part 5 — Architecture Conformance

**Status:** final. **Method:** every task in [04_BUILD_ROADMAP.md](04_BUILD_ROADMAP.md) checked against the eleven-discipline canon (Runtime Authority, Runtime Truth, Decision Evidence, Dependency Intelligence, Policy Intelligence, Context Intelligence, Intent Intelligence, Enterprise Decision Model, Canonical Fact Intelligence, Resolver Intelligence, Integrity Intelligence — the directive names nine explicitly; Resolver Intelligence and Integrity Intelligence are included here too, since a roadmap item could touch either without being named). **No violation was found in any task as currently scoped.** Several tasks carry a specific constraint that must hold when they are actually implemented — this document exists to state those constraints before implementation begins, per the directive.

## Governing principle

Every task in this roadmap is additive to, or a read-only consumer of, the existing eleven-discipline runtime. None proposes new logic inside `domain/decision/engine.py`, a new writer to `intents`/`decisions`/`evidence`, a new resolution source competing with Runtime Truth, or a new discipline. Where a task's *eventual* implementation could drift from that if built carelessly, the constraint is stated below so the drift is prevented at design time, not caught after the fact.

## Tasks with no discipline touchpoint

C1 (database migration), C4 (SOC 2 / pentest), C5 (legal documents), H2 (staging/CD), H3 (support ticketing), H4 (SDK tests in CI), H5 (API doc regeneration), L4 (second-language SDK), L5 (i18n), L6 (responsive layouts) are infrastructure, process, legal, or presentation-layer work that never reads or writes a canon-governed table and never sits in the decision path. No conformance risk exists for any of them.

## Tasks with a real touchpoint, and the constraint each must hold

### C2 — Alerting/APM/scheduled monitoring

**Touches:** observability of Runtime Authority's own execution. **Constraint:** instrumentation (Sentry, metrics, tracing) must be added at the service/router layer only — `domain/decision/engine.py` must remain free of any import beyond `dataclasses`/`typing`, exactly as Phase 2's test already enforces. Monitoring the fail-closed path from outside is conformant; instrumenting *inside* it is not, and would fail `test_decision_engine_imports_nothing_from_db_services_or_routers` immediately if attempted — the existing test is sufficient protection here, not a new one.

### C3 — Notification delivery (if implemented rather than removed)

**Touches:** consumes Decision outcomes as a trigger (e.g., "notify on DENY"). **Constraint:** notification delivery must be a downstream, decoupled consumer of an already-persisted Decision/Evidence record — never a dependency Runtime Authority's evaluation waits on, and a notification-delivery failure must never affect a Decision's outcome or delay Evidence being written. This is the same fail-closed discipline the canon already applies to OPA itself (a slow OPA times out to `HUMAN_REVIEW`; a slow webhook must never touch the Decision at all).

### H1 — Authorization Receipts (RFC-001)

**Touches:** Decision Evidence directly; reads Runtime Truth's already-resolved facts. **Verified non-violating by the RFC's own text:** §4 Non-Goals explicitly states Runtime Authority, the Evidence Portal, and governance documents are all unchanged — this is a new *output format* for Decision Evidence, not a new evaluation path. **Constraint:** (1) Receipts are an extension of Decision Evidence, not a twelfth discipline — implement as a new module consumed *after* `append_evidence` runs, never as a parallel evidence-producing path (preserving Decision Evidence's own single-shape-of-truth property). (2) The proposed Transparency Log / Merkle-anchoring component must never become a synchronous dependency of `submit_intent` — anchoring is necessarily periodic/asynchronous by the RFC's own design (§5.1), and must stay that way so a slow or unavailable anchoring service can never block a Decision. (3) Whatever new module implements this should get its own Dependency Intelligence boundary test (the same `ast`-based pattern Phases 2 and 5 already established) confirming it never imports `domain.decision` directly — it should consume `Decision`/`Evidence` objects already produced, the same relationship `evidence_service.py` already has today.

### M1 — Formatted/scheduled reporting

**Touches:** reads Decision/Evidence/Intent data. **Constraint:** report generation must be strictly read-only against all three tables — this is the practical enforcement point for the "append-only evidence"/"immutable decision" promises [45_PHASE_5_BROKEN_PROMISE_REPORT.md](../SPECIFICATION/45_PHASE_5_BROKEN_PROMISE_REPORT.md) already found hold only by convention, not by a database constraint. New code with broad read access across these tables is exactly the kind of new surface where an accidental `.update()` call could first appear; code review for this task should check for exactly that.

### M2 — Provisioning automation (dedicated instance per customer)

**Touches:** nothing at the discipline level — each provisioned instance is a fully independent deployment with its own database, so no cross-tenant boundary question arises. **No constraint beyond normal operational care.**

### M3 — Guided onboarding wizard

**Touches:** orchestrates existing organisation/principal/policy/agent creation APIs in sequence. **Constraint:** the wizard must call the same service-layer functions every other entry point uses (`organization_service`, `agent_service`, `runtime_policy_service.deploy_policy`, Compiler V2's validation) — it must never introduce a "fast path" that skips Policy Intelligence's compilation/validation or Canonical Fact Intelligence's action-vocabulary check merely because the request originated from a wizard rather than the Policy Studio UI. A wizard is a new *sequence*, not a new *authority*.

### M4 — Contract/invoice tracking

**Touches:** potentially the `Organization`/`Principal` rows Runtime Authority Context resolves from, if implemented carelessly. **Constraint, stated proactively because this is easy to get wrong silently:** billing/contract status must never become a field `resolve_runtime_authority_context` reads, directly or indirectly. If a future feature ever needs "is this customer's contract current" to affect anything, that is a new, undeclared authorization fact and must be treated as a genuine Canonical Fact Intelligence addition (named, catalogued, reasoned about) — not a column silently added to a table the Resolver already queries. Today's recommended scope (an internal, non-customer-facing tracking tool) avoids this risk entirely by not touching the governed schema at all.

### L1 — Full multi-tenancy (row-level isolation)

**Touches:** the most architecturally significant item in the entire roadmap, by far. **Constraints:**
1. Tenant scoping must be enforced in the service layer, before `decision_engine.evaluate()` is ever called — `domain/decision/engine.py` must remain exactly as pure as it is today; a tenant-id check does not belong inside it any more than a database query does.
2. `organization_id` is already a resolved fact inside Runtime Authority Context today (Phase 1/2's Authority Model) — enforcing tenant isolation on top of it is closing a gap in an *existing* fact's enforcement, not introducing a new fact. This should be documented as such when it happens, to avoid the appearance of inventing new canon.
3. Any new tenant-scoping query helper (the natural shape: a `_scoped_to_organization(...)` filter added across `agent_service`, `runtime_policy_service`, `intent_service`, `evidence_service`) should get a Dependency-Intelligence-style boundary test confirming it's applied consistently, the same way Phase 2 tested the single-writer guarantee — this is exactly the kind of "small, targeted check tied to one demonstrated risk" [43_PHASE_5_INTEGRITY_INTELLIGENCE_SPEC.md](../SPECIFICATION/43_PHASE_5_INTEGRITY_INTELLIGENCE_SPEC.md) already establishes as this codebase's practice, not a new framework.

### L2, L3 — Global search, BI dashboards

**Touches:** read-only queries across Decision/Evidence/Agent/Policy data. **Constraint:** same as M1 — read-only, no risk if kept that way; flag if either ever grows a "quick fix" write path.

## Verdict

No task in [04_BUILD_ROADMAP.md](04_BUILD_ROADMAP.md) violates any of the eleven disciplines as currently scoped. Six tasks (C2, C3, H1, M1, M4, L1) carry a specific, named constraint that must be honored at implementation time — each stated above precisely so it can be checked against the actual diff when that work happens, the same way [45_PHASE_5_BROKEN_PROMISE_REPORT.md](../SPECIFICATION/45_PHASE_5_BROKEN_PROMISE_REPORT.md) already checks existing code against named promises today.
