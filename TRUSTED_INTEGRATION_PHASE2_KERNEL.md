# Trusted Integration Architecture, Phase 2: Trusted Adapter Identity, Binding, Runtime Intent Attestation, Historical Provenance

Implements Phase 2 of the Trusted Integration Architecture: makes an APPROVED Integration Contract (Phase 1, `TRUSTED_INTEGRATION_PHASE1_KERNEL.md`) participate in a real Runtime Authority request through a separately authenticated trusted Adapter, for the first time. This document describes what actually shipped; the architecture rationale lives in the Trusted Integration Architecture report and its Founder Decisions & Design Closure Addendum, not repeated here.

## The trust claim -- read this before anything else below

A successful Adapter-mediated request means exactly this, and no more:

> An authenticated Adapter claims it observed this operation and attests these canonical values.

It does **not** mathematically prove:

- the Adapter software itself is bug-free;
- the Adapter actually sits on every possible execution path;
- another bypass path does not exist;
- the external system eventually executed the action.

Nowhere in this codebase or this document does PayReality claim it "proves the external operation occurred," "prevents bypass," "blocks the downstream action," or that "Adapter attestation proves objective truth." PayReality remains a PDP (Policy Decision Point). It was not, and is not, made a PEP (Policy Enforcement Point) by this milestone.

## What this is

Two runtime paths now exist side by side:

- **Agent-direct** (`POST /v1/intents`, `verify_agent_signature`) -- unchanged, lower-assurance, exactly as it was before this milestone.
- **Adapter-mediated** (`POST /v1/integration-runtime/intents`, `verify_integration_identity_signature`) -- new, additive. A customer-operated Adapter, authenticated as an `IntegrationIdentity` (never as an Agent), names an active `EnforcementBinding`, the origin `Agent` whose authority is being evaluated, the external operation it observed, and the canonical values it mapped using that Binding's pinned, APPROVED Integration Contract version. PayReality verifies every trust invariant below *before* Runtime Authority evaluation ever runs.

Which path authenticated a given request is always determined by which endpoint was called, never inferred from payload fields -- `Depends(verify_agent_signature)` and `Depends(verify_integration_identity_signature)` are two structurally separate FastAPI dependencies, resolved against two separate certificate tables.

## Integration Identity

`IntegrationIdentity` (`server/app/db/models.py`) is a thin, separately authenticated, customer-operated workload identity. It is **not** an Agent, cannot hold delegated organizational authority, and must never appear as a `RuntimePolicy` principal -- confirmed by construction (the model carries no `principal`/`acting_for_principal_id`-shaped field at all).

Lifecycle mirrors Agent's own proven state machine exactly (`registered -> active -> suspended -> revoked -> retired`, `integration_identity_service.py`'s `_ALLOWED_TRANSITIONS`), including terminal `revoked`/`retired` states and the same "old certificate never deleted, only one active at a time" rotation discipline. No signed audit-event ledger exists here (unlike Agent's own `AgentAuditEvent`) -- a deliberate Phase 2 scope reduction: nothing in the brief requires one, and adding it would be exactly the kind of unrequested symmetry Phase 1 already warned against.

### Certificate design

`IntegrationIdentityCertificate` is a **separate table**, not a shared row in `certificates`. `Certificate.agent_id` is `NOT NULL`, and every existing Evidence/Intent/Decision reference and constraint around it assumes exactly one kind of owner; making that column nullable and adding a second, alternate owner FK would weaken an existing, proven constraint for every Agent certificate that has ever existed, to save one small table. The crypto and rotation *implementation* is identical to Agent's own (issued -> active -> rotated/expired/revoked, `idx_integration_identity_certificates_single_active` -- the same partial-unique-index pattern as `idx_certificates_single_active`). Private keys never reach this table, or anywhere else in this codebase; only the public key is stored.

Proven against real PostgreSQL (`tests/integration/test_integration_identity_certificate_postgres.py`): rotation activates the new certificate and marks the old one `rotated` (never deleted) in the same transaction, and the partial-unique index genuinely never allows two simultaneously active certificates for one identity. SQLite cannot exercise this proof at all -- `postgresql_where` is ignored on that dialect, materializing a plain, non-partial `UNIQUE` that would reject a legitimate rotated-old/active-new pair; this is the same pre-existing divergence Agent's own Certificate already has, not something new to Phase 2.

## Enforcement Binding

`EnforcementBinding` is the runtime-deployment object: **Organization x Integration Identity x Contract Version x Environment x Allowed Agents**. Lifecycle is `draft -> active -> retired`. Creating a Binding, or even leaving one active, does **not** make PayReality a PEP -- it only ever governs what PayReality's own Runtime Authority evaluation is willing to accept as trusted input; it never reaches out to, enforces against, or observes any external system.

`EnforcementBindingAgent` is an explicit join table -- "any Agent in the org" is never allowed. For an Adapter-mediated request naming Agent X, the runtime path verifies, in order: the Adapter identity is valid and active; the named Binding exists and is active; Agent X belongs to the same organization; Agent X is in an eligible runtime state; Agent X is explicitly present in this Binding's allow-list. Any failure is an integration rejection, not a DENY, and produces no Decision.

### Activation prerequisites (all required)

`activate_binding` (`enforcement_binding_service.py`) enforces every one of: the Integration Identity is `active`; the Contract version is `approved`; the Contract version and the Identity belong to the same organization; every allowed Agent belongs to that organization (checked when added, DRAFT-only); every allowed Agent is currently eligible (`status == "active"`); the allow-list is non-empty; the environment is a non-empty string. `BindingValidationError` is raised, typed, for any violation -- proven in `tests/integration/test_enforcement_binding_lifecycle.py`.

### Immutability and exactly-one-ACTIVE-per-scope

A DRAFT Binding is fully editable (environment, pinned Contract version, Integration Identity, allow-list membership). Once ACTIVE, all of those become immutable -- editing, or adding/removing an allowed Agent, raises `BindingInvalidTransitionError`; a new Binding is required to change any of them. At most one ACTIVE Binding may exist per `(Integration Identity, Integration, source_operation, environment)` scope, enforced by a real, DB-level partial unique index (`idx_enforcement_bindings_single_active_per_scope`) requiring `integration_id`/`source_operation` to be denormalized onto `EnforcementBinding` itself (Postgres cannot express a join-dependent partial unique constraint directly). Activating a new Binding for an already-occupied scope atomically retires whichever Binding previously held it, in the same transaction, using the same bounded-retry-on-`IntegrityError` idiom `deploy_policy` established for the identical class of problem (`MAX_ACTIVATION_ATTEMPTS = 3`).

**A real, non-obvious bug was found and fixed while proving this against real PostgreSQL**: retiring the prior Binding and activating the new one are both plain `UPDATE`s on the same table, with no foreign-key relationship to force an ordering between them. SQLAlchemy's unit of work does not guarantee the "retire prior" `UPDATE` is issued before the "activate this" `UPDATE` merely because it was set first in Python; when the order came out the other way, both rows were transiently `active` at once and Postgres's non-deferred partial unique index correctly rejected it. The fix is an explicit `db.flush()` immediately after marking the prior Binding retired, before activating the new one -- reproduced failing, then fixed and reproduced passing, against real PostgreSQL (`tests/integration/test_enforcement_binding_concurrency.py`), including a genuinely concurrent two-thread race via `threading.Barrier`.

### Interaction with Phase 1's Contract retirement

Phase 1's `retire_contract_version` now additionally rejects retiring an APPROVED version that an ACTIVE Binding still references (`ContractVersionHasActiveBindingError`) -- the Binding must be retired or replaced first. A historical RETIRED Binding may keep referencing a RETIRED Contract version forever; nothing is ever hard-deleted. A DRAFT Binding referencing a version does **not** block retirement -- only an ACTIVE Binding, since only an ACTIVE Binding participates in runtime evaluation at all.

## Runtime authentication and the trusted request

`POST /v1/integration-runtime/intents` is additive; `POST /v1/intents` is untouched. The Adapter signs the whole raw request body (the same discipline `Agent.authorize()` already uses) binding: Binding identity, originating Agent identity, source operation, canonical action, resource, amount/currency where present, fact subject/counterparty, every permitted context value, timestamp, nonce, and the full request body. **Phase 2 ships a single Adapter signature only** -- there is no dual Agent+Adapter signature. The origin Agent named in the request is Adapter-attested and Binding-authorized, not independently signed on that request.

`integration_runtime_service.submit_attested_intent` performs, strictly before any Runtime Authority evaluation, and in this order:

1. Integration Identity is `active` (defense in depth beyond certificate-level checks -- a *suspended* identity's certificate is untouched by suspension, mirroring Agent's own).
2. The named Binding exists, belongs to this identity, and is `active` (cross-identity reference looks exactly like not-found, the same convention this codebase already applies to organizations).
3. The named origin Agent exists in the same organization, is currently eligible (`active`), and is explicitly present in the Binding's allow-list.
4. `source_operation` exactly matches the pinned Contract version's own -- no dynamic lookup, no fallback, no HUMAN_REVIEW routing for ambiguity.
5. `action` exactly equals the Contract's `canonical_action`.
6. Structural field consistency: if the Contract declares no extraction path for `resource`/`amount`/`currency`/`fact_subject`, the Adapter must not supply a value; if it declares a path, the value must be present. PayReality cannot cryptographically prove a supplied value corresponds to the real source payload (it never receives that payload) -- this check is the honest limit of what it *can* enforce: structural consistency with the approved Contract shape.
7. Trusted context filtering (mandatory): only context keys explicitly declared in the Contract's `context_bindings` may enter Runtime Authority evaluation. An unexpected key, or a missing required bound key, is an integration rejection -- never HUMAN_REVIEW, because the semantic request itself is incomplete, not merely ambiguous. `environment` is a reserved context key the server alone injects from the resolved Binding; a caller-supplied `environment` key is itself rejected.
8. Adapter-scoped replay protection: `idx_intents_integration_identity_nonce`, a new, separate, DB-enforced `UNIQUE(integration_identity_id, nonce)` partial index -- distinct from, and never weakening, Agent-direct's own `UNIQUE(agent_id, nonce)`. It is scoped to the identity, not the named origin Agent: reusing a nonce for a *different*, equally-allowed origin Agent under the same identity still collides (proven in `tests/integration/test_integration_runtime_path.py`). This is replay protection only -- it is explicitly not business-operation idempotency (Phase 3, not built here).

Every failure above raises `IntegrationRejectionError` or `AdapterReplayDetectedError` -- never `DENY`, never a `Decision` row, never `Evidence` claiming an evaluation that never happened.

**One deliberate, disclosed scope reduction**: unlike Agent-direct's own "suspended Agent -> HUMAN_REVIEW" special case, a suspended origin Agent named in an Adapter-mediated request is rejected pre-evaluation, not routed to HUMAN_REVIEW -- integration rejection by definition never produces a Decision, so there is nothing to route.

Once every check above passes, evaluation and Evidence are produced by the exact same shared core Agent-direct Intents already use: `intent_service._evaluate_and_record`, extracted (with zero behavior change to the existing path, verified by the full existing regression suite) from `submit_intent`'s own tail. There is no second decision engine, and no duplicated evaluation logic, anywhere in this milestone. ALLOW, DENY, and HUMAN_REVIEW are all real, reachable outcomes of an Adapter-mediated request.

## Intent provenance

`Intent.agent_id` permanently means the logical, autonomous Agent whose authority is being evaluated -- it is never replaced by the Adapter's own identity. Four new, nullable, additive columns carry Adapter provenance separately: `integration_identity_id`, `enforcement_binding_id`, `integration_contract_version_id`, `environment`. All four are immutable after creation and `NULL` for every Agent-direct Intent, including every one submitted before this migration existed. `external_operation_id` (Phase 3's business-operation idempotency) was deliberately **not** added.

## Evidence and Authorization Receipt provenance

Once an Adapter-mediated Intent reaches Runtime Authority, Evidence additively carries `integration_identity_id`, `enforcement_binding_id`, `integration_contract_version_id`, `integration_contract_content_hash` (Phase 1's own immutable hash, reused, never recomputed), `environment`, `source_operation` -- all absent for Agent-direct Evidence, exactly as before. The Authorization Receipt (`ReceiptIntegrationSummary`) surfaces the same fields, populated only when the underlying Evidence payload actually carries them -- an Agent-direct decision's receipt has `integration: null`. The Receipt's own docstring, and this document, both state the same limit: reporting this provenance is not a claim that the external operation actually executed, or that no other path to the same effect exists.

## Capability Authorization: deliberately suppressed for this path

`capability_service.issue_capability_for_decision` now raises `CapabilityNotAvailableForIntegrationIntentError` whenever the underlying Decision's Intent has a non-null `integration_identity_id` -- for an immediate ALLOW, and identically for a HUMAN_REVIEW resolved to ALLOW later. This is a deliberate default, not an oversight: issuing a Capability here would hand out an unbound downstream execution permission on top of a trust chain (Adapter attestation + Binding authorization) that Phase 2 never designed to carry that weight. Building that safely is Phase 5's enforcement-mode work, not this one's.

## Human Review

An Adapter-mediated request may legitimately reach HUMAN_REVIEW like any other. The original Decision stays HUMAN_REVIEW; resolution stays entirely separate (`resolution_service`, unchanged); the integration provenance pinned to the original Intent never changes, including at resolution time -- a later resolution cannot switch Contract version, environment, Adapter identity, or Binding.

## API surface

Additive, organization-scoped, cross-organization access indistinguishable from not-found throughout:

- `POST/GET /v1/integration-identities`, `GET /v1/integration-identities/{id}`, `GET .../{id}/certificates`, `POST .../{id}/activate|suspend|revoke|retire`, `POST .../{id}/rotate` -- gated on the new `integration_identity.manage` permission throughout.
- `POST/GET /v1/enforcement-bindings`, `GET/PATCH /v1/enforcement-bindings/{id}`, `POST/DELETE/GET .../{id}/allowed-agents[/{agent_id}]` -- gated on `integration_contract.manage` (Phase 1's own permission, reused: this is configuration, not governance approval). `POST .../{id}/activate|retire` -- gated on `integration_contract.publish` (the one real governance boundary).
- `POST /v1/integration-runtime/intents` -- gated by `verify_integration_identity_signature`, the same machine-to-machine authentication model `POST /v1/intents` already uses, deliberately not a human RBAC role (`ALLOWED_UNGATED` in `test_route_permission_gates.py` documents this explicitly, the same way it already documents `POST /v1/intents`).

## RBAC

No new role system. `integration_identity.manage` (credential lifecycle: register/rotate/suspend/revoke/retire) is granted to `Role.AGENT_ADMIN`, the closest existing machine-identity admin role -- deliberately **not** `Role.GOVERNANCE_ADMIN`, which alone holds `integration_contract.publish`. This is the critical separation-of-duties invariant this milestone requires: the role that can merely register or rotate an Integration Identity's credential must never automatically gain the authority to activate a new governed semantic runtime path. Proven in `tests/unit/test_rbac_permissions.py`.

## SDK

`payreality.Adapter` (`sdk-python/payreality/integration.py`) is additive alongside `Agent.authorize()`, which is untouched. It authenticates as an `IntegrationIdentity`, signs the same way `Agent.authorize()` does (`crypto.py`/`auth.py`, unchanged), and submits to `POST /v1/integration-runtime/intents`. `Adapter` itself does not "observe" the real external operation -- it is a tool the customer-operated Adapter code calls once it has already observed one.

`ContractShape`, optional, lets a caller declare locally which fields its pinned Contract version actually extracts, so `Adapter.attest()` can reject an obviously wrong call (an undeclared field supplied, a declared field missing, an unbound context key) before ever making a network request. This reuses Phase 1's own field-path presence/absence rule -- not a new mapping language -- and is a pure local convenience: the server's own check, described above, is what actually matters and remains authoritative even if `ContractShape` is never supplied or has gone stale.

## Migration and backwards compatibility

One additive Alembic migration (`cdc87c8bea0d`, single head, verified upgrade -> downgrade -> upgrade against real PostgreSQL): four new tables (`integration_identities`, `integration_identity_certificates`, `enforcement_bindings`, `enforcement_binding_agents`) and four new nullable columns plus one new partial-unique index on `intents`. Zero migration is required for an existing Agent-direct integrator; every new Intent field is nullable and defaults to `NULL` on every pre-existing and every new Agent-direct row.

## What Phase 3 will add (recorded now, not built)

Business-operation idempotency and `Intent.external_operation_id`; a PEP; vendor-specific connectors; discovery or capability-discovery mechanisms; mapping-drift monitoring; a workflow engine, CMDB, or iPaaS; dual Agent+Adapter signatures; any UI. None of this exists yet -- this milestone stops at Phase 2, deliberately.
