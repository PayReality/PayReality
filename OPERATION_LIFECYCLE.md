# Operation Lifecycle

The product lifecycle vertical slice (`app/services/operation_service.py`,
`app/services/operation_identity_service.py`, `app/routers/operations.py`) tracks a real-world
attempted action from authorization through whatever PayReality can actually learn about its
destination outcome. This document did not exist before a consolidation review of that feature
(eight commits, ~7,900 lines, previously undocumented) found several claims worth stating
precisely and a few worth correcting. Every claim below was checked directly against the current
code, not carried forward from a prior report.

## 1. Material-action binding

Every `Operation` carries a `material_action_digest` (`Operation.material_action_digest`,
`app/db/models.py`) -- a hash of whichever fields the caller considers materially significant for
this action. Two digest sources exist:

- **Generic**: `Intent.canonical_action_digest` (`app/domain/canonical_action.py`), always
  available for any Adapter-mediated Intent.
- **Domain-specific**: `app/domain/order_action_contract.py`'s `OrderAction`, which treats
  `supplier`/`quantity`/`buyer_account`/`delivery_location`/`unit_price` as material -- a stricter
  set than the generic digest alone enforces. A caller passes this explicitly as
  `material_action_digest` to `issue_capability_for_decision`/`issue_capability_for_reviewed_decision`
  (`capability_service.py`); omitting it falls back to the generic digest.

**Enforcement**: `record_dispatch_evidence` and `record_observation` (`operation_service.py`) both
require the caller's own claimed `material_action_digest` to match the Operation's stored one
exactly, or raise `MaterialActionMismatchError` (mapped to `409` in `operations.py`). A caller
cannot report dispatch or observation evidence against a different action than the one actually
authorized, generic or domain-specific.

## 2. Lifecycle-required versus legacy contracts

`IntegrationContractVersion.lifecycle_requirement` is one of two values: `LEGACY` (the default --
every contract version that predates this field backfills to it) or `LIFECYCLE_REQUIRED`. A prior
consolidation report described this as "opt-in per submission," which reads as contradicting the
mandatory language below -- both are true, for different scopes; this section states the boundary
precisely rather than as a single blanket claim, following a full recheck of every place an
`Intent` row can be constructed (confirmed by direct grep: exactly two -- `integration_runtime_
service.submit_attested_intent` and `intent_service.submit_intent`, no third path exists).

- **LEGACY**: `business_operation_id`/`intended_destination` are optional on a submitted Intent.
  No automatic business-operation-identity resolution or replacement-safety enforcement occurs
  for a submission that omits them. Genuinely opt-in.
- **LIFECYCLE_REQUIRED**: within its own scope (below), mandatory and unbypassable, confirmed by
  code tracing, not merely asserted. A submission missing either field is rejected *before
  authorization* -- `integration_runtime_service.submit_attested_intent` reads the contract version
  resolved server-side from the request's own `enforcement_binding_id` (`binding.
  integration_contract_version_id`), never anything the request body itself claims or names
  directly -- `AttestedIntentRequest` has no `integration_contract_version_id` field at all, so a
  caller cannot select a different, less strict version per request. A caller cannot omit,
  downgrade, or override this from the request. A second, defense-in-depth recheck exists at
  capability issuance (`capability_service._link_business_operation_attempt_if_covered`) in case
  any future code path ever constructs an Intent without going through the first gate; confirmed
  not reachable today, since no such path exists.

  **The requirement's actual scope is the `EnforcementBinding`, not the organization or the
  action.** Two real, disclosed boundaries, neither a bug in the mechanism itself:

  1. **Binding-level, not retroactive.** `lifecycle_requirement` lives on the contract *version* an
     `EnforcementBinding` is currently pointed at (`binding.integration_contract_version_id`).
     Approving a new, stricter contract version never retires or otherwise affects any other
     version (confirmed: `approve_contract_version`'s own docstring states this explicitly) --
     an existing Binding keeps enforcing whatever version it already points at until someone
     explicitly re-points it (`update_binding`). An organization with multiple Bindings for the
     same Integration can have some on `LIFECYCLE_REQUIRED` and others still on `LEGACY`
     indefinitely; "we require lifecycle protection now" describes a contract version, not
     something that retroactively locks every Binding referencing an older one.
  2. **Out of scope by construction for Agent-direct submissions.** `POST /v1/intents`
     (`intent_service.submit_intent`) has no `business_operation_id`/`intended_destination`
     parameters at all and no relationship to any `IntegrationContractVersion` -- confirmed by
     reading its full signature. `lifecycle_requirement` cannot apply there; it is not a gap in
     the check, it is a different, older, lower-assurance runtime path the check was never
     designed to cover. An organization that permits the same real-world action through *both*
     a `LIFECYCLE_REQUIRED` Adapter-mediated Binding and the Agent-direct path gets lifecycle
     protection on the former only -- exactly the kind of customer-controlled alternative
     execution path `OPERATION_LIFECYCLE.md`'s own "what this document does not claim" section
     (8) already disclaims in general, now stated concretely for this specific mechanism.

## 3. Business-operation identity and separate attempts

A `BusinessOperationIdentity` row is the stable, deduplication-relevant identity of one real-world
business operation, keyed on `(organization_id, integration_id, action, destination,
business_operation_id)` -- all five, so two unrelated action types or destinations can never
collide merely for reusing the same `business_operation_id` string.

Each *attempt* at that same identity gets its own `Operation` row, chained via
`previous_attempt_operation_id`; the identity's `current_operation_id` always points at whichever
attempt is currently governing. Concurrent first attempts at the same identity race on a real,
atomic conditional UPDATE (`operation_identity_service.advance_current_attempt`) -- the loser
re-resolves against whatever actually won and is safety-checked against it, not silently dropped.

## 4. Execution stage and outcome status are independent facts

Two separate axes, deliberately never collapsed into one field:

- **`execution_stage`**: `AUTHORIZED` -> `CLAIMED` -> `DISPATCHED`. What PayReality's own runtime
  has verified happened *on this side* (a Capability was consumed; dispatch evidence was
  reported). Strictly forward-only -- `record_dispatch_evidence` requires `CLAIMED`, so a stage
  cannot be skipped or re-entered.
- **`outcome_status`**: `UNKNOWN` -> `COMMITTED` or `TERMINALLY_NOT_COMMITTED`. What is known about
  the *destination's* outcome. An operation can sit at `execution_stage=CLAIMED` or `DISPATCHED`
  with `outcome_status` still `UNKNOWN` indefinitely -- which stage was reached says nothing about
  whether the destination ever confirmed anything.

`evaluate_replacement_safety` (`operation_service.py`) reads only `outcome_status`, by design:
an operation stuck at `CLAIMED` forever is exactly as unresolved as one stuck at `DISPATCHED` with
the same outcome.

## 5. Adapter-reported evidence versus independently verified destination evidence

**PayReality does not independently verify destination outcomes.** `evidence_assurance` records
exactly how much trust a given outcome claim carries, never more than the evidence actually
supports:

- `NONE` -- no outcome evidence yet.
- `REPORTED_UNVERIFIED` -- an unsigned relay's claim (an authenticated human via
  `Permission.OPERATION_OBSERVE`, `reporter_kind=RBAC_HUMAN`, `signature_verified=False`).
- `ADAPTER_REPORTED` -- a signature-verified Trusted Adapter's own report
  (`reporter_kind=SIGNED_ADAPTER_IDENTITY`, `signature_verified=True`). This proves what that
  Adapter *reported*, not that the destination system actually executed the action -- PayReality
  has no channel of its own to the external system (see `DECLARED_VS_OBSERVED_RECONCILIATION.md`
  for the full account of why a second, independent channel is not built).
- `MANUAL_ADJUDICATED` -- an explicit human governance override (`Permission.
  OPERATION_MANUAL_ADJUDICATE`), requiring a rationale and at least one real evidence-event
  reference on the same operation.

**Enforced, not merely documented**: `_finalize_observation_event` caps `outcome_status` at
`UNKNOWN` unless the reporter is a signature-verified Adapter -- an unsigned RBAC-human relay's own
claim, even one asserting a terminal outcome, is preserved (as `REPORTED_UNVERIFIED` evidence) but
never promoted to `COMMITTED`/`TERMINALLY_NOT_COMMITTED`.

`destination_evidence_kind` (`IntegrationContractVersion`) names the one evidence tier this
platform currently implements: `ADAPTER_OWN_OBSERVATION`. No other value is accepted (the CHECK
constraint enforces exactly this one), and none should be read as a claim of independent
destination verification -- there is only the one kind, and it is exactly what its name says.

## 6. Observation permission versus execution, safety approval, and manual adjudication

Four separate permissions, separately granted:

| Permission | Grants | Held by |
|---|---|---|
| `OPERATION_OBSERVE` | Read an Operation; report dispatch evidence or an observation (as an unsigned RBAC-human relay) | Reviewer, Governance Administrator |
| `CAPABILITY_ISSUE` | Mint a Capability (the actual authorization to execute) | Governance Administrator (and equivalent) |
| `OPERATION_SAFETY_APPROVE` | Create a `DestinationDuplicatePreventionGuarantee` -- the one, human-documented way to declare a prior attempt safe to replace outside the automatic `TERMINALLY_NOT_COMMITTED` path | Governance Administrator only |
| `OPERATION_MANUAL_ADJUDICATE` | Force `outcome_status` to a terminal value by explicit governance override | Governance Administrator only |

An observer (Reviewer, holding only `OPERATION_OBSERVE`) can relay what was reported, but cannot
manufacture a safety guarantee or a terminal outcome -- both require the stronger,
Governance-Administrator-only permissions, confirmed enforced at both the router (`Depends(
require_permission(...))`) and role-mapping (`app/domain/rbac/permissions.py`) layers, not merely
asserted in a docstring.

One disclosed design point, not a defect: `record_manual_adjudication` can overwrite an
already-`COMMITTED` operation to `TERMINALLY_NOT_COMMITTED` (or the reverse) given a rationale and
a real evidence reference -- consistent with "explicit governance override," but it does mean a
single human adjudication can retroactively change an operation's own replacement-safety
classification.

## 7. Replacement-safety conditions and enforcement points

`evaluate_replacement_safety` returns exactly one of four outcomes:

- `BLOCKED_ALREADY_COMMITTED` -- the original committed; a replacement would itself be a duplicate
  effect, never offered as safe.
- `UNSAFE_UNRESOLVED` -- the fail-closed default: outcome unresolved, no covering guarantee.
- `SAFE_TERMINAL_NON_COMMIT_PROVEN` -- sufficient evidence proves the original did not, and will
  not, commit.
- `SAFE_DUPLICATE_PREVENTION_GUARANTEED` -- a live, human-documented guarantee covers this exact
  operation, optionally restricted to a specific `IntegrationIdentity`/`EnforcementBinding` that
  the attempting caller must match exactly.

Every `SAFE_*` result still requires `requires_current_authorization=True` -- safety here never
substitutes for a fresh Intent independently evaluating to `ALLOW`.

**Two enforcement points, both real**: an explicit `replaces_operation_id` supplied at issuance
(`_enforce_replacement_safety_if_linked`), and the automatic path for every Intent that declared
`business_operation_id` (`_link_business_operation_attempt_if_covered`) -- the latter requires no
caller cooperation at all. An Intent that never declares `business_operation_id` (the LEGACY,
unlinked case) is not detected or blocked by anything here: this system claims no ability to
notice on its own that two independent, uncorrelated Intents describe the same real-world action.

**Ordering fix (this review)**: the live fail-closed rechecks at issuance (origin Agent/Organization/
IntegrationIdentity/EnforcementBinding still active) now run, and are allowed to reject, *before*
the business-operation attempt is linked -- previously, an ordinary rejection here (e.g. an Agent
suspended between Decision and issuance) could leave a committed, unclaimable Operation that
permanently blocked every future legitimate attempt at that business operation. See
`app/services/capability_service.py`'s `_precheck_issuance` for the corrected ordering and the full
failure mode it closes.

## 8. Customer responsibilities

Automatic replacement-safety and business-operation deduplication only work if the integrating
customer's own Adapter:

- Supplies the **same** `business_operation_id` + `intended_destination` on every retry of what
  is genuinely the same real-world operation, and a **genuinely new** `business_operation_id` for
  any genuinely new operation. PayReality has no independent way to tell these apart -- the
  identity namespace is exactly what the Adapter declares.
- Reports dispatch/observation evidence promptly and accurately, signed under its real
  `IntegrationIdentity`. `evidence_assurance` records what was actually reported; it cannot exceed
  what the Adapter chose to report.
- Understands the precise boundary in section 2: under a `LIFECYCLE_REQUIRED` contract version,
  `business_operation_id`/`intended_destination` are mandatory and the gate is unbypassable from
  the request. Outside that scope -- a `LEGACY` contract version, a different `EnforcementBinding`
  still pointed at an older version, or the Agent-direct runtime path entirely -- supplying them
  is optional and duplicate prevention does not happen automatically. "Duplicate prevention is
  opt-in" describes that second case only; it is not a blanket statement about every path, and
  should not be read as one.
- Understands that a `DestinationDuplicatePreventionGuarantee` is a **human-documented** safety
  fact (`Permission.OPERATION_SAFETY_APPROVE`), not something PayReality derives on its own from
  destination behavior -- creating one is a governance action with real consequences (it makes a
  replacement look safe to issue), not a passive record.

## 9. OPA timeout behavior

The Decision Engine's own OPA query timeout is a best-effort, per-phase budget against a
co-located, non-adversarial OPA -- not a strict, adversarial-safe total deadline. See
`OPA_TIMEOUT_RELIABILITY.md` for the full account (client-construction cost, read-phase timeout
semantics, and what is and is not guaranteed); not repeated here.

## What this document does not claim

- **No independent destination verification.** Every outcome fact traces back to either a
  signature-verified Adapter's own report or an explicit human override -- never a channel
  PayReality has to the destination system itself.
- **No universal duplicate detection.** Automatic protection exists only for Intents that declare
  `business_operation_id`; nothing here claims to detect duplicates across uncorrelated
  submissions, and destination-side idempotency is asserted only for the one implemented
  `destination_evidence_kind`.
- **No protection against a customer bypassing this system entirely.** PayReality authorizes and
  records what it is told; it has no visibility into, and makes no claim about, an execution path
  a customer's own systems might take outside PayReality's Capability/enforcement model.
- **No hard overall OPA deadline.** See `OPA_TIMEOUT_RELIABILITY.md`.
