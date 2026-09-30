# Real Integration Validation Plan

A concrete plan for validating the operation lifecycle (`OPERATION_LIFECYCLE.md`) against a real
destination system in a sandbox -- not a live customer environment, no real financial transactions,
no external resources created without the team's own confirmation. This is a plan, not an
implementation: nothing in this section has been built or executed.

## Candidate sandbox: Stripe test-mode PaymentIntents

**Proposed, pending confirmation** -- this codebase's own test suite already models a
`vendor_payment`/`purchase_order_create` action with `supplier`/`amount`/`currency` fields; Stripe's
PaymentIntents API is a real, well-documented, genuinely idempotent destination with a
publicly-known state machine, a real test mode (zero cost, fully isolated from Stripe's live
systems), and a real idempotency-key mechanism that gives an actual point of comparison for
PayReality's own duplicate-prevention claims -- not a synthetic stand-in.

**Information needed to actually select/confirm this**, before any work starts:

- Does the team already have a Stripe account with test-mode API access, or would one need to be
  created? (Creating one is outside what this plan authorizes on its own.)
- Is Stripe an acceptable destination for this validation given PayReality's own real customer
  base's industry mix, or would a different, domain-closer sandbox (e.g. a procurement/ERP sandbox)
  be preferred?
- Who owns the API key this integration would use, and where it would be stored (this plan assumes
  it never touches source control, matching this codebase's own existing secret-handling
  conventions).

If Stripe is not the right fit, the same plan structure applies unchanged to any sandbox with a
real, documented idempotency mechanism and a real, multi-stage status model -- those two properties
are what this plan actually needs, not anything Stripe-specific.

## The consequential action and completion criterion

**Action**: create a PaymentIntent for a fixed, small test-mode amount (e.g. $1.00, using Stripe's
own documented test card numbers -- no real money moves in test mode) against a synthetic "vendor"
resource.

**Completion criterion**: the PaymentIntent reaches Stripe's own `succeeded` status, confirmed by
querying Stripe's API directly (not merely by PayReality's own internal state) -- the whole point of
this validation is checking PayReality's own recorded outcome against an independent, real system's
own authoritative status, which the existing test suite (synthetic destinations only) cannot do.

## Destination operation identity and status semantics

Stripe's `PaymentIntent.id` (a real, Stripe-issued identifier, e.g. `pi_...`) becomes
`Operation.destination_operation_id`. Stripe's own status values
(`requires_payment_method` -> `requires_confirmation` -> `processing` -> `succeeded` / `canceled` /
`requires_action`) map onto PayReality's `execution_stage`/`outcome_status` as follows:

| Stripe status | PayReality `execution_stage` | PayReality `outcome_status` |
|---|---|---|
| PaymentIntent created, Capability not yet consumed | `AUTHORIZED` | `UNKNOWN` |
| Capability consumed, PaymentIntent confirmed (dispatch attempted) | `CLAIMED` then `DISPATCHED` | `UNKNOWN` |
| `succeeded` (Stripe-confirmed) | `DISPATCHED` | `COMMITTED` |
| `canceled` / permanently failed | `DISPATCHED` | `TERMINALLY_NOT_COMMITTED` |
| `processing` / `requires_action` (still pending) | `DISPATCHED` | `UNKNOWN` |

## Receipt, acceptance, commitment, and completion distinctions

- **Receipt**: Stripe's own synchronous API response to the confirm call (an `id` and initial
  `status`) -- proves the request was accepted for processing, not that it succeeded.
- **Acceptance**: PayReality's `execution_receipt_service` records this response as an
  `ExecutionReceipt` with `status=ACCEPTED`, exactly as the existing (synthetic) test suite already
  exercises.
- **Commitment**: only once Stripe's own status is independently re-queried (a real, out-of-band
  poll or webhook -- see below) and reports `succeeded`, does PayReality record `outcome_status=
  COMMITTED`. This is the one genuinely new thing this sandbox validation adds over the existing
  synthetic-destination tests: a real second, independent source of truth to reconcile against,
  not just the Adapter's own self-report.
- **Completion**: the operation reaches a terminal `outcome_status` (`COMMITTED` or
  `TERMINALLY_NOT_COMMITTED`) with `evidence_assurance` reflecting how that terminal status was
  obtained (`ADAPTER_REPORTED` if only the Adapter's own report ever arrives; ideally validated
  against Stripe's own independently-queried status too, though PayReality's own architecture does
  not currently have a field distinguishing "Adapter-reported and independently corroborated" from
  "Adapter-reported alone" -- this validation would surface whether that distinction is worth
  adding, not assume the answer).

## Available duplicate-prevention guarantees and their limitations

Stripe's own idempotency-key mechanism (a client-supplied key on the confirm request) prevents
Stripe itself from double-charging on a literal retried request. This is **destination-side**
idempotency, distinct from and complementary to PayReality's own `business_operation_id`-based
replacement-safety (which prevents PayReality from *issuing a second Capability* for the same
business operation, upstream of Stripe entirely). This validation would exercise both, and
explicitly test whether they compose correctly: does a PayReality-authorized retry (a legitimate
new attempt after a proven-safe replacement) reuse or regenerate the Stripe idempotency key
correctly, given the two systems have no shared understanding of each other's own identity scheme.

**Limitation, disclosed in advance**: Stripe's idempotency guarantee only covers requests using the
identical idempotency key; it does not, and cannot, prevent an operator from manually creating a
second, unrelated PaymentIntent for the same real-world intent through Stripe's own dashboard --
exactly the "no protection against a customer bypassing this system" limitation already documented
in `OPERATION_LIFECYCLE.md`, now demonstrable against a real system rather than only asserted.

## How authoritative facts are obtained and refreshed

Two options, both realistic for a sandbox validation:

1. **Polling**: PayReality (or a small reference Adapter built for this validation) queries
   `GET /v1/payment_intents/{id}` on a short interval after dispatch, feeding the result through
   the existing `record_observation` path exactly as a human-relayed or Adapter-signed report
   already does.
2. **Webhooks**: Stripe's own `payment_intent.succeeded` webhook, received by a small test
   endpoint, triggering the same `record_observation` call. More realistic of a real production
   integration, but requires a publicly reachable endpoint (e.g. an ngrok tunnel for the sandbox
   validation) -- an added piece of infrastructure this plan flags but does not build without
   confirmation.

Recommended starting point: polling, since it needs no externally reachable endpoint and directly
reuses the existing `record_observation` code path unchanged.

## Where enforcement is mandatory

The PaymentIntent confirm call to Stripe happens only after a real Capability has been issued and
consumed (`verify_and_consume_capability`) -- exactly the existing enforcement point, unchanged.
This validation adds no new enforcement point; it proves the EXISTING one against a real
destination rather than a synthetic one.

## Testing missing, delayed, and conflicting evidence

- **Missing**: confirm a PaymentIntent, then never poll/never receive the webhook (simulate a
  dropped connection) -- confirm the Operation correctly stays at `outcome_status=UNKNOWN`
  indefinitely, matching `schedule_2_unresolved_outcome_after_revocation.jsonl`'s own synthetic
  version of this same scenario, but now against a real Stripe PaymentIntent that genuinely did
  reach `succeeded` on Stripe's own side -- the interesting case is confirming PayReality does NOT
  silently infer success just because time passed.
- **Delayed**: poll immediately (Stripe usually resolves fast in test mode) and confirm PayReality
  correctly reports `UNKNOWN` in the interim, not a premature guess.
- **Conflicting**: manually construct a scenario where an unsigned RBAC-human observation claims
  `SUCCEEDED` while Stripe's own real status is still `processing` (or later resolves to
  `canceled`) -- confirm the unsigned claim is retained (as `REPORTED_UNVERIFIED`) but never
  promoted to `COMMITTED`, exactly as `_finalize_observation_event`'s existing, tested behavior
  already guarantees against synthetic evidence.

## Success and invalidation criteria

**Success**: every mapping in the status table above is observed to hold against Stripe's real,
independently-queried status at least once each (`succeeded` and `canceled` outcomes both
exercised); the missing/delayed/conflicting scenarios above all behave exactly as the existing
synthetic-destination test suite already predicts; no discrepancy is found between what the
synthetic tests claim and what the real destination actually does.

**Would invalidate the claim**: any case where PayReality's own recorded `outcome_status` diverges
from what Stripe's own independently-queried status actually was (e.g. PayReality reports
`COMMITTED` while Stripe's own status is `canceled`, or the reverse) -- that would mean the
synthetic-destination test suite's own model of destination behavior is not a faithful stand-in for
a real one, and `OPERATION_LIFECYCLE.md`'s claims would need to be revisited, not merely
re-asserted against more synthetic tests.

## What this plan does not do

Does not choose a live customer environment, create any external account or resource without the
team's own confirmation, or execute a real financial transaction (Stripe test mode moves no real
money). Does not commit to Stripe specifically -- see "information needed" above.
