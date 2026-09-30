# Stripe Test-Mode Sandbox: Concrete Implementation Plan

A single, concrete action to validate, code-independent (no Stripe API is called and no code is
written by this document). Builds on `REAL_INTEGRATION_VALIDATION_PLAN.md` (the original proposal)
and `STRIPE_SANDBOX_HANDOFF.md` (the handoff distinguishing PaymentIntent creation/confirmation/
success/settlement) -- this document adds the specific wiring an implementer needs to start:
identity/idempotency mapping, evidence retrieval, retry handling, and exactly what test mode can
and cannot prove.

## The one action being validated

A single `purchase_order_create`-style Intent, authorized through the existing lifecycle (Decision
-> Capability -> consumption), dispatched as one Stripe test-mode PaymentIntent, confirmed with a
test card, and independently re-queried until Stripe's own status resolves.

**Completion criterion, stated once and not reused loosely elsewhere**: the validation is complete
only when Stripe's own independently-queried `PaymentIntent.status` is `succeeded` (or, for the
negative case, a guaranteed-decline terminal status) AND PayReality's own `Operation.outcome_status`
matches it. A completed PaymentIntent *creation* or *confirmation* call alone does not satisfy this
-- see `STRIPE_SANDBOX_HANDOFF.md`'s own explicit distinction between the four steps.

## Trusted operation identity and idempotency-key mapping

| PayReality concept | Stripe concept | Mapping |
|---|---|---|
| `Operation.id` (PayReality's own durable identity for this attempt) | — | Not sent to Stripe; stays internal. |
| `CapabilityToken.nonce` (already a real, random, per-issuance value -- `secrets.token_hex(16)`, `app/domain/capability/token.py`) | Stripe idempotency key (`Idempotency-Key` header on the `confirm` call) | Reuse directly. One Capability is consumed exactly once (already enforced, atomically, by existing code), so its own nonce is already a correct, unique-per-attempt value -- no new identifier needs to be minted for this purpose. |
| `Operation.destination_operation_id` (existing, nullable `Text` column) | `PaymentIntent.id` (`pi_...`) | Written via the *existing* `record_dispatch_evidence` call (`operation_service.py`), passing Stripe's real `pi_...` id as `destination_operation_id` -- no schema change needed. |
| `BusinessOperationIdentity` (correlates retries of the same real-world operation) | — (Stripe has no equivalent concept) | A genuinely new attempt (a fresh Intent after a proven `TERMINALLY_NOT_COMMITTED` original) must mint a **new** Capability, and therefore a new nonce/idempotency key, for its own Stripe call -- reusing the original key would make Stripe return the *original* (failed) PaymentIntent's result instead of attempting a fresh charge. This is the one place a real implementation bug could silently defeat the validation's own purpose; call it out explicitly in code review. |

## Evidence retrieval and authentication

- **Retrieval**: `GET /v1/payment_intents/{id}` against Stripe's API, authenticated with the
  test-mode secret key (see "Setup," below) sent as the standard Stripe `Authorization: Bearer
  sk_test_...` header -- Stripe's own documented authentication, nothing PayReality-specific.
- **Feeding the result back into PayReality**: through the *existing* `record_observation` path
  (`operation_service.py` / `POST /v1/operations/{operation_id}/observations`), reported by a
  small reference poller acting as an authenticated `RBAC_HUMAN` reporter (`Permission.
  OPERATION_OBSERVE`) for this validation's own purposes -- not a new evidence-acceptance code
  path. This means the poller's own report is `REPORTED_UNVERIFIED` evidence by construction,
  *unless* a genuine `IntegrationIdentity` signs it (the stronger, `ADAPTER_REPORTED` path) --
  decide which before implementation: the weaker path proves the mechanism reaches from a real
  destination to PayReality at all; the stronger path additionally proves the signed-Adapter
  evidence path specifically, which is the more realistic production shape and the recommended
  choice if the extra setup (registering a real `IntegrationIdentity` keypair for this
  validation) is acceptable.

## Missing/delayed response and retry scenarios

| Scenario | Simulated by | Expected PayReality behavior |
|---|---|---|
| Destination never responds to the confirm call | A deliberately invalid Stripe API base URL for one call | `record_dispatch_evidence` is never called; `execution_stage` stays `CLAIMED`, never advances to `DISPATCHED` -- matches `schedule_2_unresolved_outcome_after_revocation.jsonl`'s own pattern |
| Poll arrives before Stripe has resolved | Poll immediately after confirming (Stripe usually resolves fast in test mode, but the race is real) | `outcome_status` stays `UNKNOWN`; the poller's own retry (a second poll after a short delay) is what actually produces the resolved report, not an inferred one |
| Poll transiently fails (network) | Kill the poller's own HTTP connection mid-request once | Standard retry-with-backoff at the poller level (not a PayReality concern) -- confirms this is genuinely a client-side retry, not something the lifecycle model itself needs to handle differently |
| A stale poll reports an outcome for an operation already resolved by a fresher report | Deliberately reorder two poll results | `_finalize_observation_event`'s own existing idempotent/no-op behavior for a report that adds no new information (already covered by the existing test suite; this validation just needs to confirm it holds against a real timestamp/ordering from a real system, not only a synthetic one) |

## How current authority and replacement safety will be enforced

Unchanged from the existing, already-tested mechanism -- this validation exercises it against a
real destination, it does not add a new enforcement point:

- **Current authority**: the Capability's own live fail-closed rechecks at issuance
  (`_precheck_issuance`) and consumption (the Agent/IntegrationIdentity/EnforcementBinding/
  Organization liveness checks already in `capability_service.py`) apply exactly as they do
  today. No Stripe-specific authority concept exists or is needed.
- **Replacement safety**: if the validation includes the "destination declines" fault scenario
  followed by a deliberate retry, that retry must go through `evaluate_replacement_safety`
  exactly like any other replacement -- confirming `SAFE_TERMINAL_NON_COMMIT_PROVEN` is reached
  only once Stripe's own decline is independently confirmed (not merely attempted), and that the
  retry still requires a fresh, independently-`ALLOW`-evaluated Decision (`requires_current_
  authorization`), never treated as a rubber-stamp continuation of the original.

## What test-mode behavior can and cannot establish

**Can establish**: that PayReality's own `execution_stage`/`outcome_status`/`evidence_assurance`
model correctly tracks a real, independent system's real state machine end-to-end, including the
missing/delayed/conflicting-evidence behaviors already claimed against synthetic destinations; that
the idempotency-key mapping above is sound in practice, not just on paper.

**Cannot establish**: anything about real money movement, real settlement timing, real bank
rejections, real fraud/risk holds, or any of Stripe's own live-mode-only behaviors (test mode is
explicitly designed to short-circuit real financial rails) -- none of this validation's results may
be described as proving anything about live-mode behavior. Also cannot establish whether a
*different* real destination (a genuine ERP or procurement system, closer to this platform's own
`purchase_order_create` domain than a payments processor) would expose gaps Stripe's own, payments-
specific state machine does not -- this remains a single-destination validation, not a general
proof.

## Minimum missing setup information (to be provided by the team, not this task)

1. Confirmation that Stripe test-mode is an acceptable stand-in destination (open question,
   unchanged from the prior plan).
2. Whether the stronger (`ADAPTER_REPORTED`, signed) or weaker (`REPORTED_UNVERIFIED`, RBAC-human)
   evidence path should be exercised -- affects whether a real `IntegrationIdentity` keypair needs
   to be provisioned for this validation specifically.
3. Where the `STRIPE_TEST_SECRET_KEY` environment variable should be set for whoever runs this --
   a local `.env` file (already this repo's own convention for other secrets, never committed) is
   sufficient; **do not paste the actual key value anywhere in chat, a ticket, or a commit** --
   only the variable *name* needs to be agreed on, not its value.

## Setup instructions (code-independent)

1. Obtain a Stripe test-mode secret key from the Stripe Dashboard (Developers -> API keys ->
   "Reveal test key") -- a real Stripe account action, outside this task's own scope.
2. Set it locally as `STRIPE_TEST_SECRET_KEY` (or whatever name is agreed per item 3 above) in the
   same `.env`-style mechanism this codebase already uses for other secrets -- never in source
   control, never in a ticket, never pasted into a chat.
3. No webhook endpoint is needed for the recommended polling approach; skip ngrok/webhook setup
   entirely unless the team specifically prefers the webhook approach from the original plan.

## Acceptance criteria

- Both the success (`succeeded`) and decline (guaranteed test-mode decline) destination outcomes
  are exercised at least once each, independently re-queried, and correctly reflected in
  PayReality's own `outcome_status`.
- Every fault scenario in the table above behaves as predicted.
- The idempotency-key reuse-vs-fresh-key distinction (table above) is explicitly tested, not just
  reasoned about: one genuine retry-of-the-same-attempt (same key, same PaymentIntent) and one
  genuine new-attempt-after-resolution (new key, new PaymentIntent) are both exercised.
- No divergence is found between PayReality's own recorded outcome and Stripe's own
  independently-queried outcome at any point -- any divergence found invalidates the claim (per
  `REAL_INTEGRATION_VALIDATION_PLAN.md`'s own success/invalidation criteria) and is reported, not
  hidden or explained away.

## Explicitly not done by this plan

No Stripe API call made, no PaymentIntent created, no external resource created, no payment
executed, no code written. This is a plan for a follow-up implementation task, pending the open
questions above.
