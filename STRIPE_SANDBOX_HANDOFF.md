# Stripe Test-Mode Sandbox: Implementation Handoff

A short, concrete handoff for the sandbox validation proposed in `REAL_INTEGRATION_VALIDATION_
PLAN.md`. No external resources are created and no payment is executed by this document -- it is a
handoff for a follow-up implementation task, pending the team's own confirmation of the open
questions in that plan (does the team have Stripe test-mode access already, is Stripe the right
destination at all).

## The exact action being authorized, and what is NOT the same thing

This validates PayReality's own lifecycle tracking against a real destination's real state
machine. It does **not** validate a real supplier payment, and must not be described as one. Four
genuinely distinct steps, each with its own completion criterion -- conflating them is the single
most likely way to misreport this validation's own result:

1. **PaymentIntent creation** (`POST /v1/payment_intents` on Stripe's side) -- Stripe accepts the
   request and returns a `PaymentIntent` object with `status=requires_payment_method` (or
   `requires_confirmation`, depending on how it's created). Completion criterion: a real
   `pi_...` id exists on Stripe's own side. This alone proves nothing about payment; it is the
   destination-side equivalent of `Operation` reaching `execution_stage=AUTHORIZED`.
2. **PaymentIntent confirmation** (`POST /v1/payment_intents/{id}/confirm`) -- Stripe attempts to
   charge the attached test payment method. Completion criterion: the call returns without a
   synchronous error and the PaymentIntent moves to `processing` or a terminal status. This is the
   destination-side equivalent of `execution_stage=DISPATCHED` -- dispatch attempted, outcome not
   yet known.
3. **Payment success** -- Stripe's own asynchronous processing resolves the PaymentIntent to
   `succeeded`. Completion criterion: an independently-queried `GET /v1/payment_intents/{id}`
   (or a received `payment_intent.succeeded` webhook) reports `succeeded`. This is the only step
   that maps to PayReality's `outcome_status=COMMITTED`.
4. **Settlement** -- Stripe moving captured funds to the connected account's own bank account,
   on Stripe's own payout schedule (days later, not part of this validation at all). PayReality's
   lifecycle model has no concept of settlement and this validation does not test or claim
   anything about it.

**A test confirming step 1 or 2 alone is NOT "supplier-payment validation."** Only step 3,
independently confirmed, validates what `OPERATION_LIFECYCLE.md` claims about `COMMITTED`.

## Required credentials and setup (none live yet)

- A Stripe account with test-mode API access. **Not created by this task.** If one already exists,
  only its **test-mode** secret key (`sk_test_...`) is needed -- never a live key
  (`sk_live_...`), and the test-mode key is never sufficient to move real money regardless of how
  it's used.
- The key is read from an environment variable (e.g. `STRIPE_TEST_SECRET_KEY`) at runtime, never
  committed to source control, matching this codebase's own existing secret-handling convention
  (`settings.evidence_signing_key_b64` and friends are loaded the same way).
- Stripe's own published test card numbers (e.g. `4242 4242 4242 4242` for a guaranteed success,
  `4000 0000 0000 0002` for a guaranteed decline) -- public, documented by Stripe itself, not a
  secret.
- No webhook endpoint is required for the recommended (polling) approach in
  `REAL_INTEGRATION_VALIDATION_PLAN.md`; if the team prefers the webhook approach instead, an
  ngrok (or equivalent) tunnel would be additional infrastructure requiring its own separate
  confirmation before being set up.

## Fault scenarios to exercise

| Scenario | How to trigger (test mode) | Expected PayReality behavior |
|---|---|---|
| Destination succeeds | Confirm with `4242 4242 4242 4242` | `outcome_status` reaches `COMMITTED` only after an independent re-query/webhook confirms `succeeded` -- never immediately on confirmation alone |
| Destination declines | Confirm with `4000 0000 0000 0002` | `outcome_status` reaches `TERMINALLY_NOT_COMMITTED`, not `UNKNOWN` left hanging, once the decline is independently confirmed |
| Destination requires additional authentication | Confirm with a 3D-Secure test card (Stripe publishes these) | Operation stays `outcome_status=UNKNOWN` while `requires_action`; confirms PayReality does not guess an outcome for a still-pending destination state |
| Network/API failure mid-confirmation | Point the reference Adapter at an invalid Stripe API base URL for one call | Matches `schedule_2_unresolved_outcome_after_revocation.jsonl`'s own pattern: `RECEIPT_MISSING`, never inferred as either outcome |
| Delayed webhook/poll | Deliberately delay the first poll by several minutes | `outcome_status` stays `UNKNOWN` for the entire delay, not inferred early |

## Destination evidence and idempotency conditions to test

- Confirm the SAME PaymentIntent twice with the SAME idempotency key (Stripe's own mechanism) --
  expect Stripe itself to return the original result, not create a second charge. This is
  destination-side idempotency, separate from and layered under PayReality's own
  `business_operation_id`-based replacement-safety (see `OPERATION_LIFECYCLE.md` section 7).
- Confirm that a PayReality-authorized *replacement* attempt (a new Intent, new Decision, new
  Capability, following a proven-`TERMINALLY_NOT_COMMITTED` original) generates a **new**
  idempotency key for its own Stripe call, not a reused one -- reusing the original key would
  incorrectly return the original (failed) PaymentIntent's own result instead of attempting a
  fresh charge.

## Success criteria

Every mapping in `REAL_INTEGRATION_VALIDATION_PLAN.md`'s status table is observed at least once
against Stripe's own real, independently-queried status (both a `succeeded` and a `canceled`
outcome exercised); every fault scenario above behaves exactly as PayReality's existing
synthetic-destination test suite already predicts; `effect_count`/`outcome_status` are never
reported ahead of what Stripe's own independently-queried state actually confirms.

## What would invalidate the claim

Any divergence between PayReality's own recorded `outcome_status` and Stripe's own independently-
queried status at the same point in time (see `REAL_INTEGRATION_VALIDATION_PLAN.md` for the full
account of why this specifically is the thing that would matter).

## Remaining assumptions, to be confirmed before implementation starts

- That Stripe test-mode PaymentIntents is an acceptable stand-in destination for the team's own
  purposes (see the open question in `REAL_INTEGRATION_VALIDATION_PLAN.md` -- this has not been
  confirmed).
- That polling (not webhooks) is an acceptable mechanism for this validation's own scope (avoids
  needing a publicly reachable endpoint).
- That no real money movement is acceptable to the team as "sufficient" validation -- this plan
  deliberately never proposes moving real funds, even in small amounts, since test mode already
  gives a real state machine without that risk.

## Explicitly not done by this handoff

No Stripe account created, no API key requested or generated, no PaymentIntent created or
confirmed, no code written. This is a specification for a follow-up implementation task.
