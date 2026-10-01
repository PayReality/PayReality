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
retention behavior) and `server/tests/integration/test_stripe_sandbox_operation_lifecycle.py` (15
scenarios, all passing against the real PayReality lifecycle service layer + a real,
genuinely-generated-and-verified Ed25519 signature for the signed-Adapter reporting path, and the
local Stripe simulation -- never a real network call).

**A real flaw in the first "corrected" mapping was found and fixed in this pass** (see the mapping
section below for the full account): the first correction keyed the idempotency key off
`Operation.id` alone, which is wrong in exactly one real scenario -- a replacement authorized
despite the original's own outcome still being UNKNOWN (a human-documented duplicate-prevention
guarantee, not a proven non-commit). A regression test
(`test_replacement_authorized_despite_unresolved_outcome_carries_forward_the_same_destination_
identity`) reproduces the exact failure mode against the pre-fix design and proves the fix directly.

**Not executed, and not attempted, in this session**: any real call to Stripe's own API. No
`STRIPE_TEST_SECRET_KEY` was configured anywhere in this environment (confirmed directly: no
`STRIPE_*` environment variable exists here), and per this review's own explicit instruction,
real Stripe execution requires both that key and `STRIPE_SANDBOX_EXECUTE=true` to be set --
neither is, so `build_real_client_from_env()` returns `None` and nothing in the adapter can reach
Stripe. This is confirmed by its own test
(`test_real_stripe_client_requires_explicit_test_mode_key_and_execution_switch`), not merely
asserted in prose.

**What "15 passed" means, precisely**: all fifteen are LOCAL, against `FakeStripeBackend` (or, for
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

## Trusted operation identity and idempotency-key mapping (corrected, revision 2)

**History, stated precisely so the mistake is not repeated:**

1. The *original* version of this plan proposed reusing `CapabilityToken.nonce` directly as the
   Stripe idempotency key. Wrong: a capability nonce identifies an *authorization artifact*, and a
   fresh, PayReality-authorized retry of the same logical operation mints a brand-new nonce while
   still referring to the same real-world destination operation -- the nonce-keyed design would
   give every attempt, including illegitimate ones, its own fresh Stripe-level scope.
2. The *first correction* (implemented in commit `e1aeeb8`) keyed the idempotency key off
   `Operation.id` instead, reasoning that a fresh, PayReality-authorized attempt should always get
   a fresh Stripe-level scope. **This is correct for only one of the two ways a replacement attempt
   gets authorized, and wrong for the other.** `evaluate_replacement_safety` returns one of two
   distinct `SAFE_*` outcomes, and they are NOT interchangeable for this purpose:
   - `SAFE_TERMINAL_NON_COMMIT_PROVEN` -- the original is *proven*, by real evidence, to have
     failed to commit. A fresh Stripe-level scope here is correct and safe: there is no risk of a
     duplicate effect from an original proven never to have taken effect.
   - `SAFE_DUPLICATE_PREVENTION_GUARANTEED` -- a human has documented that a replacement is safe
     *despite* the original's own outcome still being `UNKNOWN` (the real, existing escape hatch,
     `record_destination_duplicate_prevention_guarantee`, for exactly the case where a response was
     lost before PayReality ever learned the resulting Stripe object id). Here, the original's own
     create call may well have *actually succeeded* on Stripe's side -- PayReality simply never
     found out. Giving the replacement a fresh `Operation.id`-derived key reproduces, under a
     different name, the exact duplicate-effect risk the nonce-keyed design already had: Stripe
     would see two unrelated keys and create two independent PaymentIntents for what is actually
     one destination operation.

   Traced via this exact sequence (this review's own task): (1) Operation A dispatches; Stripe
   creates a PaymentIntent. (2) The response is lost before A's own `destination_operation_id` is
   ever durably recorded. (3) `A.outcome_status` stays `UNKNOWN`. (4) A human records a guarantee;
   a fresh Capability/Operation B is authorized. (5) The adapter dispatches again for B. Under the
   `Operation.id`-keyed design, step 5 uses a brand-new key, unrelated to whatever key A's own
   (lost) create call used -- if A's create call actually succeeded, step 5 creates a second
   PaymentIntent. **Reproduced and fixed in this pass** -- see
   `test_replacement_authorized_despite_unresolved_outcome_carries_forward_the_same_destination_
   identity`, which fails against the pre-fix design and passes against the fix.

**The fix: a fourth, computed identity -- `destination_dispatch_identity`.** Not `Operation.id`
itself, but the result of walking the replacement chain backward from the current `Operation.id`:
carry the identity forward through any predecessor whose own outcome is still unresolved (an
`UNKNOWN`-outcome predecessor means this dispatch is really a continuation of the same, never-
resolved destination attempt), and mint a genuinely fresh identity only at a predecessor *proven*
`TERMINALLY_NOT_COMMITTED` (a real break point). A pure, ORM-free function
(`destination_dispatch_identity(operation_id, chain)` in `scripts/stripe_sandbox_adapter.py`) --
the adapter itself has zero dependency on SQLAlchemy/`app.db.models`; a caller supplies the chain
from whatever `Operation` rows it has already loaded.

Verified against Stripe's own official documentation
([Idempotent requests](https://docs.stripe.com/api/idempotent_requests),
[Advanced error handling: Idempotency](https://docs.stripe.com/error-low-level#idempotency),
[Retrieve a PaymentIntent](https://docs.stripe.com/api/payment_intents/retrieve)), not assumed:

- **Retention**: keys are pruned after **24 hours**; reuse after pruning "generates a new
  request" -- i.e. no protection at all past that window. This review adds an explicit guard
  (`DispatchWindowExpiredError` / `ensure_dispatch_window_still_valid`) so PayReality's own adapter
  refuses to dispatch past this window while the outcome is still unresolved, rather than silently
  relying on a key Stripe itself would treat as brand new.
- **Parameter matching**: reusing a key with different parameters than the original request
  produces an explicit error (not a silent duplicate, not the new parameters silently applied).
  Fixed this pass to fingerprint only *material* parameters (amount, currency; payment method for
  confirm) -- metadata (which legitimately differs between two attempts sharing a carried-forward
  destination identity, e.g. `operation_id`/`capability_nonce`) is correlation-only and must never
  itself trigger a mismatch error.
- **Concurrent requests**: a second request using a key still executing under the first
  returns **HTTP 409 Conflict** -- an explicit, safe rejection, not a race that could double-book.
- **Key-value guidance, directly from Stripe's own docs**: "Derive the key from a user-attached
  object, like the ID of a shopping cart" -- Stripe itself recommends deriving the key from a
  **stable, pre-existing business object's identity**, not a fresh, per-call token. This directly
  validates `destination_dispatch_identity` over a raw `Operation.id`.
- **Retrieval has no metadata-search recovery path**: `GET /v1/payment_intents/{id}` is a plain
  lookup keyed on an already-known `pi_...` id -- there is no documented way to recover a lost
  PaymentIntent id by searching metadata. This is why recovery from a lost create response must be
  "retry the same create call with the same key" (Stripe's own cache resolves it), never "search
  for it by metadata" -- a design point this review's regression test exercises directly.
- **Scope**: per Stripe account. A single Stripe account shared by multiple PayReality tenants is
  handled by embedding `organization_id` and `integration_id` **directly in the key string itself**
  (not relying on metadata alone, per this review's own explicit requirement) -- see
  `test_wrong_tenant_cannot_reuse_or_redirect_an_identity`.
- **GET/DELETE** are idempotent by definition and never take a key; only mutating `POST` calls
  (create, confirm) need one, naturally separating status lookup from any effectful call.

### The corrected mapping (revision 2) -- six distinct identities

| # | Concept | Value | Stable across... | Sent to Stripe as |
|---|---|---|---|---|
| 1 | **Business operation** | `BusinessOperationIdentity.id` | Every attempt at the same real-world operation, forever | `metadata.payreality_business_operation_identity_id` |
| 2 | **Authorized attempt** | `Operation.id` | One real authorization (one Decision, one Capability) -- a new attempt always gets a new value | `metadata.payreality_operation_id` |
| 3 | **Capability nonce** | `CapabilityToken.nonce` | Nothing -- identifies the single-use authorization artifact consumed for *this* call | `metadata.payreality_capability_nonce` |
| 4 | **Logical destination operation** (new this revision) | `destination_dispatch_identity(operation_id, chain)` -- NOT always equal to #2 | Carried forward across a replacement authorized despite an unresolved (`UNKNOWN`) predecessor outcome; genuinely fresh only past a predecessor *proven* `TERMINALLY_NOT_COMMITTED` | `metadata.payreality_destination_dispatch_identity` |
| 5 | **Stripe object id** | `PaymentIntent.id` (`pi_...`) | N/A -- durable once learned | `Operation.destination_operation_id`, written back via the existing `record_dispatch_evidence` call |
| 6 | **Stripe idempotency key** | `f"{organization_id}:{integration_id}:{destination_dispatch_identity}:{operation_kind}"` | Repeated calls that resolve to the SAME #4 + the same Stripe call (create vs. confirm) | `Idempotency-Key` header -- never equal to #2 or #3 directly, and never derived from them alone |

### Why this satisfies every property required of a stable destination-operation identity

- **Unchanged across retries, including newly authorized attempts, in the one case where that
  matters for duplicate prevention**: `destination_dispatch_identity` (#4) -- not metadata alone --
  is what Stripe's own idempotency layer keys on, so a replacement authorized despite an unresolved
  original correctly resumes the same Stripe-level scope rather than minting an unrelated one.
- **Tenant- and account-scoped directly in the key, not only via metadata**: `organization_id` and
  `integration_id` are embedded literally in the `Idempotency-Key` string itself (#6) -- even a
  hypothetical cross-tenant collision in #4 could never produce a colliding Stripe-level key.
- **Distinguishes creation from confirmation**: the `operation_kind` suffix guarantees these are
  always different Stripe-level operations, never sharing a scope.
- **A retry that finds an existing object does not automatically proceed to confirmation**: the
  orchestration is split into `create_or_resume_payment_intent` (idempotent create only) and
  `confirm_payment_intent_if_pending` (confirms only if the resumed object is still
  `requires_payment_method`; otherwise returns it unchanged, `confirmation_skipped=True`).
- **Does not confuse two legitimate purchases with identical material fields**: identity is
  derived entirely from the Adapter-declared `business_operation_id` (via `BusinessOperationIdentity`,
  #1), never from material content -- two genuinely different orders sharing every material field
  still get different, non-colliding identities as long as the Adapter declares different
  `business_operation_id` values for them.
- **Rejects material changes presented as a retry, without false-positiving on metadata**: the
  simulated parameter-mismatch check now fingerprints only material parameters (see above);
  correlation metadata legitimately differing between two attempts sharing #4 is never mistaken
  for a mismatch.
- **Does not rely on the idempotency key past its protection window**: `ensure_dispatch_window_
  still_valid` blocks a dispatch attempt outright once 24 hours have elapsed since the first
  dispatch for this #4 chain, if the outcome is still unresolved -- rather than silently
  dispatching under cover of a key Stripe itself would treat as brand new. Longer-term,
  business-level protection against re-attempting a *resolved* operation remains
  `evaluate_replacement_safety`'s job, unchanged, layered underneath this guard.

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
- [Retrieve a PaymentIntent](https://docs.stripe.com/api/payment_intents/retrieve) -- confirmed a
  plain GET keyed on an already-known `pi_...` id, no idempotency key accepted or needed, and no
  documented metadata-search recovery path -- directly informs why recovery from a lost create
  response must retry the same call with the same key, never search by metadata.

## Explicitly not done by this plan or its implementation

No real Stripe API call made, no PaymentIntent created against a real Stripe account, no external
resource created, no live payment executed. The adapter and its local-simulation tests ARE
implemented (see "Implementation status" above); what remains is the real-Stripe-test-mode
execution, blocked on the credential/switch described there.
