# Merge Review: Operation Lifecycle

Branch `product-lifecycle-opa-timeout-reliability`, merge base `90e41df` (main) through this
branch's final head. This is the final pre-merge review; it does not repeat the full investigative
narrative of the two prior consolidation passes (see git log for those commits' own messages) --
it states what is now true, what was found and fixed across all passes, and what remains open.

## Migration ordering, schema consistency, existing-data compatibility

- **Fixed**: `a7c3e9f1b5d6`'s `down_revision` pointed at a migration (`f3a5c7e9b1d4`) that exists
  only as uncommitted content on an unrelated branch. Any checkout containing only this branch's
  own committed history could not build its own migration graph (`alembic heads`/`upgrade head`
  failed with `KeyError`). Re-pointed to the real committed predecessor (`e2c4b6d8f1a3`).
- **Fixed**: `operation_evidence_events.evidence_reference_ids` was `JSONB` in the ORM model but
  plain `JSON` in the migration that created it -- the one place this codebase's own JSONB
  convention was missed. Corrected in the migration.
- **Verified**: full migration chain applies cleanly to a real, empty PostgreSQL database and to
  one seeded with realistic pre-existing data (`integration_contract_versions` rows predating the
  new `lifecycle_requirement`/`destination_evidence_kind` columns) -- the backfill correctly
  assigns `LEGACY`/`ADAPTER_OWN_OBSERVATION` to pre-existing rows, and both columns land `NOT NULL`
  with their `CHECK` constraints in place. Full downgrade path also verified against
  data-populated tables.

## Tenant boundaries and permission enforcement

No cross-tenant access found anywhere in the reviewed code (two independent review passes, plus a
direct check of every new code path added by this session's own fixes). Every query and identity
computation that needs `organization_id` scoping has it; the one case that looks unscoped
(`Operation.decision_id` lookups with no explicit `organization_id` filter) is safe because
`decision_id` only ever reaches these functions after an upstream, already-org-scoped resolution
(`intent_service.get_decision_for_organization`). Router-level permission gates
(`CAPABILITY_ISSUE`, `OPERATION_OBSERVE`, `OPERATION_SAFETY_APPROVE`,
`OPERATION_MANUAL_ADJUDICATE`) match the role/permission mapping and were confirmed reachable and
correctly rejecting through the real router functions (`test_lifecycle_router_reachability.py`).

## Issuance ordering and rollback behavior

- **Fixed (critical)**: business-operation-identity linking (creating an `Operation`, advancing
  the identity's `current_operation_id` -- both committed durably) used to happen *before* the
  live fail-closed freshness rechecks. An ordinary, expected rejection there (e.g. an Agent
  suspended between Decision and issuance) left a permanently orphaned, unclaimable Operation that
  blocked every future legitimate attempt at that business operation. Fixed by extracting the
  freshness checks into `_precheck_issuance`, called before linking in both issuance paths
  (`issue_capability_for_decision` and `issue_capability_for_reviewed_decision`). A regression
  test (`test_issuance_freshness_rejection_never_orphans_the_business_operation_identity`)
  reproduces the original failure against the pre-fix code and proves the fix directly.
- **Fixed (medium-high)**: `create_operation_for_decision`'s check-then-insert had no
  `IntegrityError` handling, unlike the identical race shape already guarded elsewhere in this
  same feature. Two concurrent issuance calls for the same Decision could produce an unhandled
  500. Fixed to match the established pattern; the router now also catches the resulting typed
  error (previously unhandled there too).
- **Verified, no defect**: capability consumption's own rollback/atomicity
  (`verify_and_consume_capability`'s conditional `UPDATE ... WHERE consumed_at IS NULL`) and
  issuance's idempotency-safe insert (`_issue_and_persist`'s pre-check + `IntegrityError` handling)
  are both real, DB-enforced guarantees, not merely asserted.

## Operation identity and concurrent attempts

Verified clean. `BusinessOperationIdentity`'s uniqueness (`organization_id`, `integration_id`,
`action`, `destination`, `business_operation_id`) prevents cross-tenant or cross-action-type
collisions. `advance_current_attempt`'s atomic conditional UPDATE, with a bounded retry and
re-evaluation against whatever actually won, correctly handles a genuine concurrent first-attempt
race (proven with two real OS processes, `RUSLAN_COMPARISON_PACKAGE/traces/
operation_attempt_registration_concurrency.jsonl`).

## Evidence acceptance and manual adjudication

Verified clean. `_finalize_observation_event` correctly caps `outcome_status` at `UNKNOWN` unless
the reporter is a signature-verified Adapter -- an unsigned relay's claim is retained but never
promoted to a terminal value. `record_manual_adjudication` requires a real rationale and at least
one real evidence-event reference on the same Operation, and is reachable only through
`Permission.OPERATION_MANUAL_ADJUDICATE`. One disclosed design point, not a defect: a manual
adjudication can move outcome_status between the two terminal values (`COMMITTED` <->
`TERMINALLY_NOT_COMMITTED`), which is consistent with "explicit governance override" but worth
knowing for anyone building on top of `evaluate_replacement_safety`.

## Replacement-safety enforcement at issuance and consumption

Verified clean, including a check this review added: replacement-safety
(`evaluate_replacement_safety`, the four-outcome evaluation) is correctly an issuance-time-only
concern -- it decides whether issuing a *new* Capability that would supersede a prior, unresolved
operation is safe. Consumption has its own, differently-scoped check
(`verify_still_current_attempt`, called from `record_claim` before any state mutation), which
confirms the operation being claimed hasn't been superseded since issuance. These are two
different questions, each correctly asked at the right moment; consumption does not need to
re-litigate replacement-safety because nothing about a replaced operation's own safety changes
based on when the replacing one is consumed.

## The lifecycle-required protection boundary (this review's own primary task)

A prior report's "opt-in per submission" and an earlier report's "mandatory under
LIFECYCLE_REQUIRED" are **both correct, for different scopes** -- reconciled and stated precisely
in `OPERATION_LIFECYCLE.md` section 2 (see that file for the full account). Summary:

- **Mandatory and unbypassable, confirmed by code tracing** (not merely asserted): for traffic
  through an `EnforcementBinding` currently pointed at a `LIFECYCLE_REQUIRED` contract version.
  Confirmed exactly two places construct an `Intent` row in the entire codebase; the
  Adapter-mediated one reads the server-resolved contract version, never anything the request
  names or claims, and the request schema has no field that could select a different version.
- **Two real, disclosed scope boundaries**, neither a bug in the mechanism: (1) the requirement is
  a property of the specific `EnforcementBinding`'s currently-pointed-at contract version, not
  retroactive across an organization's other Bindings still on an older version; (2) the
  Agent-direct runtime path (`POST /v1/intents`) has no relationship to Integration Contracts at
  all and cannot be covered by this mechanism by construction.
- No code fix was needed for the mechanism itself; the fix in this pass is documentation
  precision, applied to `OPERATION_LIFECYCLE.md`, the comparison package's matrix, and the draft
  message.

## API and documentation consistency

Router permission gates match service-layer assumptions (confirmed via
`test_lifecycle_router_reachability.py`, calling the real router functions with real permission
dependencies, not just the underlying services). `OPERATION_LIFECYCLE.md` is now the authoritative
architecture document for this feature and is cross-referenced from `INTEGRATION_KIT.md` and
`DECLARED_VS_OBSERVED_RECONCILIATION.md`; one stale "not built" claim in `INTEGRATION_KIT.md` (a
reconciliation-results read surface that now exists via `GET /v1/operations/{operation_id}`) was
corrected in the prior pass.

## Inclusion of all required files / no dependency on unrelated uncommitted content

Verified directly: an isolated git worktree checked out from this branch's own committed history
alone (no access to the unrelated "Authority Extraction Safety Remediation" branch's uncommitted
files sitting in the same working directory) builds a single, unambiguous migration head and runs
this branch's own full test suite cleanly. This is the concrete proof that nothing in this
branch's own history silently depends on content that isn't actually committed to it.

## What remains open (not blockers, disclosed limitations)

- No independent verification of a destination outcome (architectural, not a defect --
  `DECLARED_VS_OBSERVED_RECONCILIATION.md`).
- Duplicate-attempt protection does not cover the Agent-direct runtime path, or an
  `EnforcementBinding` an organization has not yet re-pointed to a `LIFECYCLE_REQUIRED` contract
  version (see the boundary section above).
- No shutdown cleanup of the shared OPA HTTP client (`OPA_TIMEOUT_RELIABILITY.md`, disclosed,
  low-risk, unrelated to this feature's own correctness).
- The Adapter-mediated router endpoint's own signature-verification dependency
  (`verify_integration_identity_signature`) has never been exercised via a genuine ASGI/TestClient
  request anywhere in this codebase's test history (a pre-existing, repository-wide convention,
  not something this review introduced) -- confirmed via direct service-level testing and code
  tracing instead, consistent with that established convention.

## Verdict

No remaining material defects found. The two critical/high-severity issues found across this
branch's review passes (the broken migration chain, the issuance-ordering orphan bug) are fixed
and covered by regression tests. Ready for human review and merge, pending the decision-maker's
own sign-off -- this review does not itself constitute production certification.
