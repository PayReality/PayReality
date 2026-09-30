# Stripe Test-Mode Sandbox: Concrete Implementation Plan

Builds on `REAL_INTEGRATION_VALIDATION_PLAN.md` (the original proposal) and
`STRIPE_SANDBOX_HANDOFF.md` (the handoff distinguishing PaymentIntent creation/confirmation/
success/settlement) -- this document adds the specific wiring an implementer needs: identity/
idempotency mapping, evidence retrieval, retry handling, and exactly what test mode can and cannot
prove.

## Implementation status

**Implemented**: `scripts/stripe_sandbox_adapter.py` (the corrected identity/idempotency mapping
below, a `RealStripeClient` gated behind a real test-mode key + an explicit execution switch, and
a `FakeStripeBackend` local simulation modeling Stripe's own documented idempotency/concurrency/
retention behavior) and `server/tests/integration/test_stripe_sandbox_operation_lifecycle.py` (the
eleven scenarios this review's own task list required, all passing against the real PayReality
lifecycle service layer + a real, genuinely-generated-and-verified Ed25519 signature for the
signed-Adapter reporting path, and the local Stripe simulation -- never a real network call).

**Not executed, and not attempted, in this session**: any real call to Stripe's own API. No
`STRIPE_TEST_SECRET_KEY` was configured anywhere in this environment (confirmed directly: no
`STRIPE_*` environment variable exists here), and per this review's own explicit instruction,
real Stripe execution requires both that key and `STRIPE_SANDBOX_EXECUTE=true` to be set --
neither is, so `build_real_client_from_env()` returns `None` and nothing in the adapter can reach
Stripe. This is confirmed by its own test
(`test_real_stripe_client_requires_explicit_test_mode_key_and_execution_switch`), not merely
asserted in prose.

**What "12 passed" means, precisely**: all twelve are LOCAL, against `FakeStripeBackend` (or, for
one test, a plain Python object implementing only the read-only method) -- proof that this
adapter's own orchestration logic is correct, not proof that real Stripe test mode behaves as
documented. The retention/parameter-matching/concurrency facts the simulation models are each
cited to Stripe's own official documentation (see "Official sources" below); reproducing them
against a real Stripe test-mode account remains outstanding, blocked on the credential above.

## The one action being validated

A single `purchase_order_create`-style Intent, authorized through the existing lifecycle (Decision
-> Capability -> consumption), dispatched as one Stripe test-mode PaymentIntent, confirmed with a
test card, and independently re-queried until Stripe's own status resolves.

**Completion criterion, stated once and not reused loosely elsewhere**: the validation is complete
only when Stripe's own independently-queried `PaymentIntent.status` is `succeeded` (or, for the
negative case, a guaranteed-decline terminal status) AND PayReality's own `Operation.outcome_status`
matches it. A completed PaymentIntent *creation* or *confirmation* call alone does not satisfy this
-- see `STRIPE_SANDBOX_HANDOFF.md`'s own explicit distinction between the four steps.

## Trusted operation identity and idempotency-key mapping (corrected)

**The original version of this plan proposed reusing `CapabilityToken.nonce` directly as the
Stripe idempotency key. This was wrong, and is corrected here.** A capability nonce identifies an
*authorization artifact* (one Capability, consumed exactly once). A fresh, PayReality-authorized
retry of the same logical operation -- following the system's own documented "each attempt gets
its own Intent/Decision/Capability/Operation" model -- mints a brand-new Capability with a
brand-new nonce, *while still referring to the same real-world destination operation*. Using the
nonce as the idempotency key would therefore give every single attempt, including illegitimate
ones, its own fresh Stripe-level scope -- Stripe would never recognize a second attempt as
"the same operation," defeating the entire purpose of destination-side idempotency. Verified
against Stripe's own official documentation
([Idempotent requests](https://docs.stripe.com/api/idempotent_requests),
[Advanced error handling: Idempotency](https://docs.stripe.com/error-low-level#idempotency)),
not assumed:

- **Retention**: keys are pruned after **24 hours**; reuse after pruning "generates a new
  request" -- i.e. no protection at all past that window.
- **Parameter matching**: reusing a key with different parameters than the original request
  produces an explicit error (not a silent duplicate, not the new parameters silently applied).
- **Concurrent requests**: a second request using a key still executing under the first
  returns **HTTP 409 Conflict** -- an explicit, safe rejection, not a race that could double-book.
- **Key-value guidance, directly from Stripe's own docs**: "Derive the key from a user-attached
  object, like the ID of a shopping cart. This provides a relatively straightforward way to
  protect against double submissions" -- Stripe itself recommends deriving the key from a
  **stable, pre-existing business object's identity**, not a fresh, per-call token. This directly
  validates the corrected design below, rather than the original nonce-based one.
- **Scope**: per Stripe account (test-mode and live-mode keys are structurally separate
  credentials, so environment separation is automatic; a single Stripe account shared by multiple
  PayReality tenants is the real scoping concern this design must handle explicitly).
- **GET/DELETE** are idempotent by definition and never take a key; only mutating `POST` calls
  (create, confirm) need one, naturally separating status lookup from any effectful call.

### The corrected mapping

| Concept | Value | Stable across... | Sent to Stripe as |
|---|---|---|---|
| **Destination-operation identity** (audit/correlation only, never the idempotency key itself) | `BusinessOperationIdentity.id` (existing, already tenant/integration/action/destination-scoped by its own DB unique constraint -- reused, not re-derived) | Every attempt at the same real-world operation, original and all retries, including a fresh PayReality-authorized attempt after the original is proven `TERMINALLY_NOT_COMMITTED` | Stripe `metadata.payreality_business_operation_identity_id` |
| **Idempotency key** (the actual `Idempotency-Key` header) | `f"{operation.id}:{operation_kind}"`, where `operation_kind` is `"payment_intent_create"` or `"payment_intent_confirm"` (never reused between the two -- they are different Stripe calls with different parameters, so sharing a key between them would hit Stripe's own parameter-mismatch error) | Repeated calls for the **same** attempt only (e.g. a client-side network-error retry of the same `Operation`'s own confirm call) -- **deliberately NOT** reused for a new, PayReality-authorized attempt, which gets its own new `Operation.id` and therefore its own fresh Stripe-level scope, so Stripe actually attempts a fresh charge rather than replaying a stale/declined result | `Idempotency-Key` header |
| **Attempt identity** (audit only) | `Operation.id` | One specific attempt (already embedded in the idempotency key above) | Stripe `metadata.payreality_operation_id` |
| **Capability nonce** (audit only, kept **separate** from both identities above, per this review's own explicit requirement) | `CapabilityToken.nonce` | Nothing -- it identifies the authorization artifact consumed to make *this one* call, not the operation itself | Stripe `metadata.payreality_capability_nonce` |
| **Tenant/environment scope** (audit only) | `organization_id`, `integration_id` | N/A | Stripe `metadata.payreality_organization_id` / `payreality_integration_id` |
| `Operation.destination_operation_id` (existing, nullable `Text` column) | `PaymentIntent.id` (`pi_...`) | N/A | Written back via the *existing* `record_dispatch_evidence` call -- no schema change needed |

### Why this satisfies every property required of a stable destination-operation identity

- **Unchanged across retries, including newly authorized attempts**: the *business-level*
  correlation (`BusinessOperationIdentity.id`, sent as metadata) is identical across every attempt
  at the same real-world operation, so a human or a reconciliation job can always trace a Stripe
  object back to the logical operation it belongs to -- satisfied by metadata, not by literal
  idempotency-key reuse (which would be actively harmful, per the retention/replay analysis above).
- **Tenant- and account-scoped**: `BusinessOperationIdentity.id` is already unique per
  `(organization_id, integration_id, action, destination, business_operation_id)` -- reusing its
  existing, already-tested uniqueness guarantee rather than re-deriving a new one by hand.
- **Distinguishes creation from confirmation**: the `operation_kind` suffix on the idempotency key
  guarantees these are always different Stripe-level operations, never sharing a scope.
- **Does not confuse two legitimate purchases with identical material fields**: identity is
  derived entirely from the Adapter-declared `business_operation_id` (via `BusinessOperationIdentity`),
  never from material content (amount, supplier, etc.) -- two genuinely different orders that
  happen to share every material field still get different, non-colliding identities as long as
  the Adapter declares different `business_operation_id` values for them (its own responsibility,
  unchanged from the existing architecture).
- **Rejects material changes presented as a retry**: because the *real, current* parameters are
  still sent on every call alongside the derived key, Stripe's own parameter-mismatch check (not
  a new PayReality mechanism) safely errors if a caller bug ever reused a key with different
  material parameters, rather than silently processing a different charge under cover of "a retry."
- **Does not rely on the idempotency key past its protection window**: the key is scoped per
  *attempt* (`Operation.id`), and a dispatch attempt is expected to resolve at the transport level
  (create -> confirm) within seconds to minutes, not hours -- nowhere close to Stripe's 24-hour
  pruning window. Longer-term protection against re-attempting a *resolved* business operation is
  explicitly **not** Stripe's job here: it is `evaluate_replacement_safety`'s (already-existing,
  already-tested) job, which refuses to authorize a new Capability for an unresolved or
  already-committed prior attempt regardless of how much time has passed. The two mechanisms are
  layered deliberately: Stripe's key gives short-term, transport-level safety for one attempt;
  PayReality's own replacement-safety gate gives long-term, business-level safety across attempts.

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

## Official sources verified for this plan's own design

- [Idempotent requests](https://docs.stripe.com/api/idempotent_requests) -- retention (24 hours),
  parameter-matching behavior, key-generation guidance (including the "derive from a stable
  object, like a shopping cart ID" recommendation this design's corrected mapping follows),
  GET/DELETE exemption.
- [Advanced error handling: Idempotency and retries](https://docs.stripe.com/error-low-level#idempotency) --
  concurrent-request behavior (HTTP 409), treatment of cached `4xx`/`5xx` results, the
  metadata-correlation pattern for reconciling a request whose result was never received.
- [Create a PaymentIntent](https://docs.stripe.com/api/payment_intents/create) -- request/response
  shape (`id`, `status`, `metadata`, `amount`, `currency`) the `FakeStripeBackend` simulation
  models.

## Explicitly not done by this plan or its implementation

No real Stripe API call made, no PaymentIntent created against a real Stripe account, no external
resource created, no live payment executed. The adapter and its local-simulation tests ARE
implemented (see "Implementation status" above); what remains is the real-Stripe-test-mode
execution, blocked on the credential/switch described there.
