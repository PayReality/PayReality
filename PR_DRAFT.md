Draft only -- prepared for a draft PR targeting `main`. Not merged.

---

## Title

Operation lifecycle: mandatory duplicate-attempt protection for lifecycle-required integrations

## The concrete problem and resulting behavior

Before this branch, PayReality had no way to track a real-world attempted action across retries,
and no way for an integration to require duplicate-attempt protection rather than merely offer it.
An Adapter retrying a timed-out request had no mechanism tying the retry to the original attempt,
and nothing stopped a second, independent Capability from being issued for the same real-world
operation if the first attempt's outcome was still unknown.

This branch adds: a stable `BusinessOperationIdentity` correlating every attempt at the same real-
world operation; `execution_stage`/`outcome_status`/`evidence_assurance` tracked as independent
facts (what PayReality itself verified vs. what is known about the destination vs. how strong that
knowledge is); automatic replacement-safety enforcement that blocks issuing a new Capability for an
unresolved prior attempt; and a per-contract `lifecycle_requirement` switch making all of this
mandatory, not merely available, for integrations that need it.

## Mandatory protection for configured lifecycle-required bindings

For an `EnforcementBinding` currently pointed at an `IntegrationContractVersion` with
`lifecycle_requirement=LIFECYCLE_REQUIRED`, supplying `business_operation_id` and
`intended_destination` is mandatory and unbypassable from the request. Confirmed by tracing every
place an `Intent` row can be constructed in the codebase (exactly two) and reading the actual
enforcement code, not asserted from the docstring: the check reads the contract version resolved
server-side from the binding, never anything the request body names or claims, and the request
schema has no field that could select a different, less strict version. A submission missing
either field is rejected before authorization, with a second, defense-in-depth recheck at
capability issuance.

## Exclusions (what mandatory protection does *not* cover, and why)

Three real, disclosed scope boundaries -- none a bug in the mechanism itself, each a genuine limit
worth a reviewer's attention:

1. **Legacy bindings.** A binding still pointed at a `LEGACY`-tagged contract version enforces
   nothing here; supplying `business_operation_id` is optional, and omitting it is allowed.
   Approving a new, stricter contract version never retroactively affects a binding that hasn't
   been explicitly re-pointed to it -- an organization can have some bindings on
   `LIFECYCLE_REQUIRED` and others still on `LEGACY` for the same integration, indefinitely.
2. **The separate Agent-direct path.** `POST /v1/intents` (`intent_service.submit_intent`) has no
   `business_operation_id` concept at all and no relationship to any Integration Contract --
   `lifecycle_requirement` cannot apply there by construction, not by oversight. An organization
   that permits the same real-world action through both a `LIFECYCLE_REQUIRED` binding and the
   Agent-direct path gets protection on the former only.
3. **A new business identity supplied for what is actually the same real-world action.**
   PayReality trusts the Adapter's own declared `business_operation_id` completely -- it has no
   independent way to tell that two different declared identities actually describe one real
   operation. If an Adapter's own retry logic generates a fresh `business_operation_id` instead of
   reusing the original one, this mechanism cannot detect or prevent the resulting duplicate
   attempt; the identity namespace is exactly what the Adapter declares, nothing more.

## Adapter-reported evidence versus independent destination verification

PayReality does not independently verify a destination outcome anywhere in this branch.
`evidence_assurance=ADAPTER_REPORTED` proves what a signature-verified Adapter reported, not that
the destination system actually executed the action -- there is no channel of PayReality's own to
the destination. An unsigned, RBAC-authenticated human relay's claim is retained (`evidence_
assurance=REPORTED_UNVERIFIED`) but never promoted to a terminal `outcome_status`
(`_finalize_observation_event` enforces this cap; confirmed in code, not merely documented).

## Postgres migration and concurrency evidence

- Full migration chain verified against a real, empty PostgreSQL database and, separately, one
  seeded with realistic pre-existing `integration_contract_versions` rows predating the new
  columns -- confirming the backfill (`LEGACY`/`ADAPTER_OWN_OBSERVATION`) behaves correctly against
  real existing data, not only an empty schema. Full downgrade path also verified.
- Two distinct concurrency scenarios proven with real, independent OS processes (never mocked):
  capability-consumption race (two connections racing to consume the same token) and
  operation/attempt-registration race (two processes racing to register the first attempt at a
  brand-new business-operation identity). Both traces: `RUSLAN_COMPARISON_PACKAGE/traces/`.

## Prior validation: full suite, clean worktree

**1,166 passed, 0 failed (1 confirmed-flaky timeout, not reproducing in isolation)** -- re-run this
pass specifically because production code changed (the new `stripe_sandbox_dispatch_windows` table,
its model and service module, and the migration that creates it -- see "Dispatch window anchoring"
in `STRIPE_SANDBOX_IMPLEMENTATION_PLAN.md`): run from a freshly re-synced isolated git worktree
containing exclusively this branch's own committed history, at commit `43388fb` plus this session's
own uncommitted additions, 2026-10-01. One test (`test_simulator_warns_instead_of_silently_guessing_
when_no_counterparty_given`) failed under the full run with an OPA HTTP timeout and passed cleanly
when re-run in isolation immediately after -- an environmental flake under the full run's resource
contention (an ephemeral OPA server per test), unrelated to anything in this pass (that test touches
policy simulation, not Operations/dispatch windows), not a real regression.

Superseded citation, no longer the operative baseline: **1,147 passed, 0 failed** at commit
`f612e2f`, 2026-09-30 (this branch's own committed history only, excluding an unrelated,
uncommitted branch's own ~90 tests that inflated an earlier, informal count).

## Subsequent focused reproduction checks

Re-run from a freshly re-synced clean worktree immediately before this publication, to confirm
nothing regressed between `f612e2f` and the final head: the critical-fix regression test
(`test_issuance_freshness_rejection_never_orphans_the_business_operation_identity`), the
`LIFECYCLE_REQUIRED` rejection test (`test_lifecycle_required_contract_rejects_missing_business_
operation_id`), and the router-reachability test (`test_lifecycle_router_reachability.py`) --
all passed.

## Remaining limitations and outstanding work

- **Partially validated against a real destination system now, scoped narrowly and precisely** -- a
  Stripe test-mode sandbox adapter (`scripts/stripe_sandbox_adapter.py`) and its test suite (21
  scenarios, `test_stripe_sandbox_operation_lifecycle.py`: 20 local-simulation, 1 against Stripe's
  real test-mode API) are implemented and passing, including a revised identity/idempotency-key
  mapping (`STRIPE_SANDBOX_IMPLEMENTATION_PLAN.md`) that fixes a real duplicate-effect gap found in
  an earlier pass's own "corrected" design, a durable race-safe dispatch-window anchor (proven
  against a real Postgres database), and a live Stripe account-binding check. **A genuine, real
  PaymentIntent CREATION call ran against Stripe's test-mode API this pass**, once the user securely
  configured a real `rk_test_...` credential directly (never pasted into chat; two earlier,
  different values that WERE pasted into chat were never used for any call -- whether those two
  values have since been revoked in the Stripe Dashboard is not established by anything available to
  this review and requires the user's own confirmation, not yet given). The real run is a
  SERVICE-LAYER integration test (PayReality's own HTTP/ASGI submission API, routing, and
  authentication middleware are not exercised here or anywhere in this test suite, a pre-existing
  convention) that calls the Stripe create primitive directly, not the full dispatch orchestration --
  meaning the window-expiry and account-binding guards were not invoked against the real API this
  pass, and no observation/reconciliation step was ever recorded for the real dispatch (`outcome_
  status` stays `UNKNOWN`). It found and fixed two real bugs no local simulation had caught (a
  metadata key exceeding Stripe's real 40-character limit; metadata that varied per attempt and
  broke the exact carried-forward-key recovery scenario this design exists to make safe), and
  established exactly 2 real test-mode PaymentIntent objects were created across 3 invocations (2
  failing, 1 passing) -- see `STRIPE_SANDBOX_IMPLEMENTATION_PLAN.md`'s own "External execution: what
  actually ran" and "Test-resource inventory" sections for the full, separated account. PaymentIntent
  confirmation, decline/3-D-Secure handling, and the account-binding/window-expiry guards against
  genuinely different real accounts/elapsed time remain unverified against the real API -- disclosed
  under "Remaining unverified behavior" in that same document, not claimed as proven.
- No shutdown cleanup of the shared OPA HTTP client (disclosed, low-risk, unrelated to this
  feature's own correctness -- `OPA_TIMEOUT_RELIABILITY.md`).
- The Adapter-mediated router endpoint's own signature-verification dependency has never been
  exercised via a genuine ASGI/TestClient request anywhere in this codebase (a pre-existing,
  repository-wide testing convention, not introduced by this branch) -- verified instead via
  direct service-level testing and code tracing.

Full detail on all of the above: `MERGE_REVIEW.md`.

This PR is not a production certification. It closes the review and fix cycle for this feature and
makes it ready for human review; real-destination validation remains outstanding and is proposed,
not completed, work.
