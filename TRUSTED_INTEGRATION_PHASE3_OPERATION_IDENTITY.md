# Trusted Integration Architecture, Phase 3: Business Operation Identity

Implements Phase 3 of the Trusted Integration Architecture: business-operation idempotency for the trusted-Adapter runtime path established in Phase 2 (`TRUSTED_INTEGRATION_PHASE2_KERNEL.md`). This document describes what actually shipped.

## The gap this closes

Phase 2's Adapter-scoped nonce replay protection answers "have I already received this exact authenticated request?" -- not "have I already made a Runtime Authority decision for this real-world operation?" An Adapter retrying the same external operation with a fresh timestamp and a fresh nonce could, before this milestone, produce a second Decision, a second Evidence record, or a second HUMAN_REVIEW item for one real action. Phase 3 closes that gap with a first-class `external_operation_id`, required on every Adapter-mediated request, that identifies the real external business operation across retries.

## Scope: organization + integration + environment + external_operation_id

Deliberately **not** scoped by `enforcement_binding_id` (a Binding is replaceable configuration -- retiring one and activating a replacement must not reset idempotency) or `integration_identity_id` (rotating or replacing the Adapter identity must not either). Organization scoping is implicit: `integration_id` is a UUID primary key belonging to exactly one `Integration` row, which belongs to exactly one organization, so a partial unique index on `(integration_id, environment, external_operation_id)` is already correctly organization-scoped without a redundant stored column. `integration_id` on `Intent` is server-derived from the resolved Contract version at submission time -- the caller never chooses it.

## The canonical operation fingerprint

The authority-relevant *meaning* of the operation, computed server-side and never trusted from the caller beyond the individual fields that produce it: origin Agent id, the Integration Contract's deterministic `content_hash` (never `IntegrationContractVersion.id` -- two independently approved versions with identical semantic content must not manufacture a false conflict), `source_operation`, `canonical_action`, `resource`, a Decimal-normalized `amount` (quantized to the same 2-decimal precision `Intent.amount` is actually persisted and compared at, so `100.1`/`100.10`/a float-precision artifact all normalize identically), `currency`, the fact-subject identifier (`counterparty`, not the resolved fact *value* -- facts may legitimately change over time while the underlying business operation stays the same), and the Contract-bound trusted context. `environment` is excluded (it is already the uniqueness scope); nonce, timestamp, `correlation_id`, `IntegrationIdentity`/certificate id, and `EnforcementBinding` id are all excluded -- none of them are part of what the operation *means*. Canonical JSON (sorted keys, recursing into nested context values) then SHA-256, the same "hash the canonical serialization" shape Phase 1's own Contract `content_hash` already established.

**Section 5's mandatory correction**: the origin Agent's identity is part of the fingerprint. Agent A and Agent B may both be allowed through the same Adapter and Binding while holding different organizational authority -- a retry naming a different origin Agent produces a different fingerprint and therefore conflicts, rather than silently returning Agent A's Decision as though it satisfied Agent B's own authority check. This is enforced structurally by the fingerprint's own field list, not by a separate manual comparison.

## Basic semantics

A new scoped `external_operation_id` runs the normal Adapter-mediated flow and persists its operation identity and fingerprint alongside the Intent. An existing one with the **same** fingerprint returns the original Decision -- no re-evaluation, no new Decision, no new Evidence, no new Capability, no provenance change. An existing one with a **different** fingerprint fails closed with a typed `ExternalOperationConflictError`, itself a pre-evaluation integration conflict: never evaluated, never a DENY, never Evidence claiming an evaluation that never happened.

**Decisions are immutable across policy and fact changes.** A retry carrying the same `external_operation_id` and the same fingerprint returns the original Decision even if organizational policy was redeployed, or a Trusted Enterprise Fact changed, in between -- proven directly (not just asserted) by call-count instrumentation showing `decision_engine.evaluate` and `fact_service.resolve_facts` are invoked exactly once across an original submission and any number of matching retries, and separately by realistic end-to-end tests: a policy redeployed from DENY to ALLOW between attempts still returns the original DENY; a Trusted Enterprise Fact changed from `true` to `false` between attempts still returns the original ALLOW. If the external system genuinely intends a new attempt evaluated under current authority, it must use a new `external_operation_id`.

**Contract replacement**: a retry through a Binding pointing at a *semantically identical* replacement Contract version (same `content_hash`, different row) returns the original Decision; a Binding pointing at a version with genuinely different semantic content conflicts. The original Intent, Evidence, and Receipt continue referencing the original Contract version either way -- a matching retry never rewrites historical meaning under whatever Contract happens to be bound today.

## Transaction and concurrency strategy

At most one committed business operation exists per `(integration_id, environment, external_operation_id)` for Adapter-mediated requests, enforced by a real, DB-level partial unique index (`idx_intents_external_operation_scope`, `WHERE external_operation_id IS NOT NULL`) -- not merely an application-level check-then-insert. A dedicated operation-registry table was considered and rejected: `Intent` already carries every field a registry table would need, and a second table would only duplicate that data with no correctness advantage.

The idempotency check runs in two layers: a read-only fast path (the common case -- a real retry never needs to construct an `Intent` row at all) and an authoritative re-check after a racing `IntegrityError` on the real index. A collision is disambiguated by re-querying for the specific row the operation-scope index would have produced: if it now exists, this was a genuine concurrent operation race, resolved identically to the fast path (return the winner's Decision on a matching fingerprint, conflict on a mismatch); if it still does not exist, the collision could only have been Phase 2's own `(integration_identity_id, nonce)` index, surfaced as the pre-existing `AdapterReplayDetectedError`, unchanged.

**A real, non-obvious concurrency bug was found and fixed while proving this against real PostgreSQL** (distinct from, and in addition to, the one already fixed in Phase 2's own `EnforcementBinding` activation): none was actually needed here, because Intent/Decision/Evidence already commit as a single atomic unit (the same transaction boundary Phase 2 already established) -- the fix required for Phase 2's retire-then-activate UPDATE ordering does not recur here, since this path is a single INSERT racing against another single INSERT on the same unique index, which Postgres already serializes correctly with no additional flush ordering needed.

Two different `external_operation_id` values under the same Integration never serialize against each other: the partial unique index only contends when the exact same three-part scope is targeted, so N genuinely simultaneous, genuinely independent operations proceed independently, proven directly by timing (all landing well under a serialization-would-be-slow threshold).

## Failure handling

A request rejected for integration-trust reasons (invalid signature, inactive Binding, unapproved Contract, unlisted Agent, malformed context, a source-operation/canonical-action mismatch, or a malformed `external_operation_id` itself) never reaches the point where an `Intent` row is constructed at all -- the `external_operation_id` is never poisoned, and a corrected retry may use it immediately. Format validation of `external_operation_id` itself runs first, before any DB lookup, folded into the same `IntegrationRejectionError` taxonomy as every other pre-evaluation failure.

If integration validation succeeds (the Intent row, with its provenance and fingerprint, is flushed) but the transaction fails before Decision/Evidence commit, the whole transaction rolls back together -- this relies on the existing transaction boundary (one session, one commit at the end of `_evaluate_and_record`) rather than a second, loosely coupled state machine. Proven with real failure injection: a monkeypatched `decision_engine.evaluate` raising mid-evaluation leaves zero rows behind after rollback, and a subsequent real retry with the same `external_operation_id` succeeds as a brand-new operation.

## HUMAN_REVIEW, ALLOW, DENY

A pending HUMAN_REVIEW retry returns the same pending Decision, never a second review item. A resolved HUMAN_REVIEW retry returns the original Decision (still `HUMAN_REVIEW` -- the outcome itself is never rewritten) with its actual current resolution state, corrected at the router layer to check for an existing `DecisionResolution` row rather than assuming a HUMAN_REVIEW outcome always means still-pending (true only for a *brand-new* submission, not necessarily for an idempotent return of an older one). ALLOW and DENY retries return the original Decision unchanged; ALLOW retries mint no Capability -- Phase 2's Adapter-mediated Capability suppression is untouched.

## SDK

`payreality.Adapter.attest()` now requires an explicit `external_operation_id` -- the SDK never generates one. A randomly generated value on every retry would defeat the entire point of idempotency; the customer's own Adapter integration is responsible for a value that remains stable across retries (an ERP transaction id, an orchestrator execution id, a tool-call execution id, or a value it constructs deterministically when the source system provides none). Client-side validation mirrors the server's own bounds (non-empty, non-whitespace, a bounded maximum length) as a pre-flight convenience only; the server's own check remains authoritative. `Agent`/`Agent.authorize()` are completely unchanged.

## Evidence and Receipt

Evidence additively binds both `external_operation_id` and the `canonical_operation_fingerprint` for cryptographic historical proof of "this Decision was associated with this external operation id and this exact authority-relevant canonical meaning" -- never proof the external action itself executed. The Authorization Receipt exposes `external_operation_id` for a trusted-Adapter-backed Decision; the internal fingerprint is deliberately **not** exposed there (no strong debugging/audit reason to, per the brief) -- Evidence's own signed payload already carries it. Agent-direct Receipts are unaffected (`integration: null`, as before Phase 3).

## Observability

`integration_runtime_service` logs one structured line per Adapter-mediated request classifying it as `NEW`, `IDEMPOTENT_RETURN`, or `CONFLICT`, carrying only `integration_id`/`environment`/`external_operation_id` -- never amount, resource, context, or any other payload content. No new telemetry platform was introduced; this follows the exact `logging.getLogger("payreality.<domain>")` convention already established elsewhere in this codebase (e.g. `agent_service.py`).

## Backwards compatibility

Agent-direct requests are completely unaffected: `external_operation_id` is not accepted, required, or in any way meaningful on `POST /v1/intents`; `Intent.external_operation_id`/`integration_id`/`canonical_operation_fingerprint` are nullable and additive, NULL for every existing row and every Agent-direct row going forward. Because this platform has zero real external Adapter adopters today (confirmed repeatedly across this project's own history), `external_operation_id` is made a **hard requirement** on the trusted-Adapter runtime endpoint rather than a soft, optional migration path -- the stronger, correct behavior the brief asked for when compatibility does not force a weaker one.

## Migration

One additive Alembic migration (`a1f3e9c72b6d`, single head, verified upgrade -> downgrade -> upgrade against real PostgreSQL): three new nullable columns on `intents` (`external_operation_id`, `integration_id`, `canonical_operation_fingerprint`) plus the new partial unique index. `external_operation_id`/`Intent.integration_id` (business-operation idempotency) are exactly what Phase 1's own document already named as future work -- built now, on schedule.

## What Phase 4 will add (recorded now, not built)

A PEP; enforcement/Capability integration for the Adapter-mediated path; vendor-specific connectors; any UI. None of this exists yet -- this milestone stops at Phase 3, deliberately.
