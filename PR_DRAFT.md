Draft only -- not submitted as a remote PR. For review before creating one.

---

## Title

Operation lifecycle: business-operation identity, execution-stage/outcome tracking, and
replacement-safety enforcement (with consolidation fixes)

## Summary

Adds a vertical slice tracking a real-world attempted action from authorization through whatever
PayReality can learn about its destination outcome: stable business-operation identity across
retries, `execution_stage`/`outcome_status`/`evidence_assurance` as independent facts,
automatic replacement-safety enforcement for lifecycle-covered Intents, and a
`LIFECYCLE_REQUIRED`/`LEGACY` contract-level switch that makes this mandatory (not merely
available) for integrations that opt into it.

This PR also includes a full consolidation review of the feature (previously unreviewed and
undocumented across its own 8 original commits), which found and fixed two real defects -- see
"Fixed in this review" below -- before this is considered ready for merge.

## What's included

- `operations`, `operation_evidence_events`, `business_operation_identities`,
  `destination_duplicate_prevention_guarantees` tables, and the service/router layer built on
  them (`app/services/operation_service.py`, `app/services/operation_identity_service.py`,
  `app/routers/operations.py`).
- `integration_contract_versions.lifecycle_requirement`/`destination_evidence_kind`.
- RBAC: `OPERATION_OBSERVE`, `OPERATION_SAFETY_APPROVE`, `OPERATION_MANUAL_ADJUDICATE`, separately
  granted and enforced.
- `OPERATION_LIFECYCLE.md` -- the architecture document for this feature (did not exist before
  this review).

## Fixed in this review (not present in the original feature commits)

1. **Critical**: the migration chain was broken for any checkout containing only this branch's
   own committed history (`a7c3e9f1b5d6`'s `down_revision` referenced an uncommitted migration
   from an unrelated branch). Fixed.
2. **Critical**: an ordinary, transient capability-issuance rejection (e.g. a suspended Agent)
   could permanently orphan a business operation, blocking every future legitimate attempt at it.
   Fixed by reordering freshness checks before business-operation linking. Regression test
   included, proven against the pre-fix code.
3. **Medium-high**: an unhandled concurrency race in Operation creation (now a typed,
   caller-classifiable error, matching this feature's own established pattern elsewhere).
4. **Medium**: a JSON/JSONB schema mismatch in one migration.

Full detail: `MERGE_REVIEW.md`.

## The lifecycle-required protection boundary, stated precisely

`LIFECYCLE_REQUIRED` is mandatory and unbypassable for traffic through an `EnforcementBinding`
currently pointed at that contract version (confirmed by tracing every place an `Intent` row can
be constructed -- there are exactly two, and the check reads the server-resolved contract, never
the request). It is scoped to that binding, not retroactive across an organization's other
bindings, and does not apply to the separate Agent-direct runtime path. See
`OPERATION_LIFECYCLE.md` section 2.

## Validation

- Migration chain: verified against a real, empty PostgreSQL database and one seeded with
  realistic pre-existing data; full downgrade path also verified.
- Full backend suite, isolated worktree (this branch's own committed tests only): **1,147
  passed, 0 failed**.
- New tests this review: `test_issuance_freshness_rejection_never_orphans_the_business_operation_
  identity` (proves the critical fix), `test_lifecycle_router_reachability.py` (proves the feature
  is reachable through real router functions and real permission checks, not only direct service
  calls).
- Concurrency proven with real, independent OS processes (not mocked): capability-consumption race
  and operation/attempt-registration race, both in `RUSLAN_COMPARISON_PACKAGE/traces/`.

## Known limits (disclosed, not blockers)

- No independent verification of a destination outcome -- every commitment fact traces back to
  an Adapter's own signed report or an explicit human override.
- Duplicate-attempt protection does not cover the Agent-direct path or a binding not yet
  re-pointed to a `LIFECYCLE_REQUIRED` contract version.
- Not validated against a real destination system yet -- see `REAL_INTEGRATION_VALIDATION_PLAN.md`
  and `STRIPE_SANDBOX_HANDOFF.md` for the proposed next step.

## Not included / explicitly out of scope

Shutdown cleanup of the shared OPA HTTP client; a genuine ASGI/TestClient test harness for the
signature-verified Adapter-mediated router endpoint (this repository's existing, established
testing convention relies on direct service-level calls plus code tracing for that boundary, not
introduced or changed by this PR); any real-destination integration (proposed as a follow-up, not
built here).
