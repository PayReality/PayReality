# Stripe Test-Mode Sandbox: Concrete Implementation Plan

Builds on `REAL_INTEGRATION_VALIDATION_PLAN.md` (the original proposal) and
`STRIPE_SANDBOX_HANDOFF.md` (the handoff distinguishing PaymentIntent creation/confirmation/
success/settlement) -- this document adds the specific wiring an implementer needs: identity/
idempotency mapping, evidence retrieval, retry handling, and exactly what test mode can and cannot
prove.

## Implementation status

**Implemented**: `scripts/stripe_sandbox_adapter.py` (the corrected identity/idempotency mapping
below, a durable dispatch-window anchor and Stripe account binding check -- revision 3, see its own
section below -- a `RealStripeClient` gated behind a real test-mode key + an explicit execution
switch, and a `FakeStripeBackend` local simulation modeling Stripe's own documented idempotency/
concurrency/retention behavior) and `server/tests/integration/test_stripe_sandbox_operation_
lifecycle.py` (21 scenarios: 20 run purely against the real PayReality lifecycle service layer + a
real, genuinely-generated-and-verified Ed25519 signature for the signed-Adapter reporting path, and
the local Stripe simulation -- never a real network call; the 21st makes a genuine call to Stripe's
real test-mode API, gated on real credentials actually being configured -- see "External execution"
below for what it found and fixed).

**A real flaw in the first "corrected" mapping was found and fixed in an earlier pass** (see the
mapping section below for the full account): that correction keyed the idempotency key off
`Operation.id` alone, which is wrong in exactly one real scenario -- a replacement authorized
despite the original's own outcome still being UNKNOWN (a human-documented duplicate-prevention
guarantee, not a proven non-commit). A regression test
(`test_replacement_authorized_despite_unresolved_outcome_carries_forward_the_same_destination_
identity`) reproduces the exact failure mode against the pre-fix design and proves the fix directly.

**Two further gaps found and fixed this pass (revision 3)**, both in how that fix was actually
anchored and scoped -- see "Dispatch window anchoring and Stripe account binding" below for the
full account:
1. The dispatch window's own 24h-conservative guard was anchored to `Operation.created_at` (set at
   capability-issuance time), not the real first-dispatch moment -- a real gap between issuance and
   an Adapter actually dispatching would make the guard fire too early relative to Stripe's own
   real window, or (worse, if ever inverted) too late. Fixed with a new, durable, set-once table
   (`stripe_sandbox_dispatch_windows`) recording the REAL first-dispatch timestamp, never reset by
   a later replacement or a concurrent racer -- proven race-safe against a real Postgres database
   (not merely asserted), see "Implementation status" in `STRIPE_SANDBOX_HANDOFF.md`.
2. Embedding `organization_id`/`integration_id` in the idempotency key (revision 2) is not
   sufficient on its own to catch a rotated credential that now resolves to a DIFFERENT Stripe
   account -- Stripe scopes idempotency keys per account, so reusing the same key against a
   different account does not collide, it silently creates an independent object. Fixed with an
   explicit, live `retrieve_account()` check inside `dispatch_payment_intent` itself, comparing
   against the account bound at this destination identity's own first dispatch
   (`StripeAccountBindingMismatchError` on mismatch) -- plus a structural `livemode` rejection on
   every PaymentIntent object, independent of and in addition to the existing sk_test_-prefix
   credential check.

**Real Stripe test-mode execution has now run, for the first time this session**, once a genuine
test-mode credential was securely configured (never pasted into chat -- see "External execution:
what actually ran" below for the full account, including two real bugs this uncovered that no
amount of local simulation had caught). The sections below separate LOCAL simulation evidence from
ACTUAL external evidence explicitly -- never blended, per this review's own requirement.

### Local simulation

`server/tests/integration/test_stripe_sandbox_operation_lifecycle.py`: **20 of 21 tests** run
purely against `FakeStripeBackend` (or, for a few, no I/O at all) -- proof that this adapter's own
orchestration logic is correct, not proof that real Stripe test mode behaves as documented. The
21st (`test_real_stripe_payment_intent_creation_only_against_live_test_mode_api`) is the one
exception -- see below.

### External execution: what actually ran

**A real, genuine network call to Stripe's own test-mode API happened in this session**, scoped
exactly to this review's own narrow authorization: PaymentIntent **creation only**, no automatic
confirmation, capture, or settlement claim.

**Credential provenance, stated precisely.** Two values were pasted directly into the chat
conversation earlier in this engagement (character-for-character identical to each other -- the
second paste was not a genuine rotation, it was the same value re-sent). **Neither was ever used for
any call in this adapter, this test, or anywhere in this session** -- confirmed directly: the actual
credential used was a Stripe **restricted key** (`rk_test_...`, a different value, Stripe's own
currently-recommended credential type over a full `sk_test_...` secret key), which the user typed
directly into `server/.env` themselves, never through this conversation. Whether the two
originally-exposed values had actually been revoked in the Stripe Dashboard could not be
established from local evidence alone (the key material itself cannot be queried for its own status
without using it, which this review would not do, and the user's own statement after the first
exposure -- "ive rotated it" -- was followed immediately by pasting the identical, unchanged value
again, which contradicted a completed rotation having actually happened at that point). **Confirmed
directly by the user, after being asked**: both originally-exposed values have since been revoked.

**Scope of what was actually exercised -- and what was not.** `_authorize_and_consume` (the test's
own helper, shared with every other test in this file) calls `runtime_svc.submit_attested_intent`
and `capability_service.issue_capability_for_decision`/`verify_and_consume_capability` as direct
Python service-layer calls -- there is no ASGI/HTTP request anywhere in this test, matching this
entire test suite's own established, disclosed convention (no TestClient/ASGI harness exists
anywhere in this repository). **This is a service-layer integration test exercising the real
Decision/Capability/Operation/replacement-safety code paths, not a claim that the actual HTTP
submission API, its routing, or its request-authentication middleware were exercised.** Within that
scope, genuinely real: authority evaluation (a real ephemeral OPA instance), capability issuance and
consumption, business-operation and destination-identity resolution (real DB rows, real chain-walk),
replacement-safety enforcement (`evaluate_replacement_safety`, reached both automatically via
issuance and explicitly via `record_destination_duplicate_prevention_guarantee`), and the Stripe
create call itself.

**Two things this specific test does NOT exercise, disclosed precisely:**
- It calls `adapter.create_or_resume_payment_intent` directly, not the full `adapter.dispatch_
  payment_intent` orchestration. This means `ensure_dispatch_window_still_valid` (the 24h guard) and
  the live account-binding comparison inside `dispatch_payment_intent` itself were **never invoked
  against the real API** -- calling `create_or_resume_payment_intent`/`retrieve_status` directly was
  the only way to stay within creation-only scope, since the full orchestration would also attempt a
  confirm call. Both guards remain verified only against `FakeStripeBackend` (see "Remaining
  unverified behavior" below, which already said this; stated here with the precise reason).
- No observation or reconciliation step was ever recorded for the real dispatch: the test never
  calls `record_dispatch_evidence`, `record_observation`, or anything in `execution_reconciliation_
  service`. `verify_and_consume_capability` does advance `execution_stage` to `CLAIMED` as part of
  its own atomic consumption (this happens automatically, real code, not skipped), but it never
  reaches `DISPATCHED`, and `outcome_status` stays `UNKNOWN` for the whole test. A real Stripe object
  was created; PayReality's own Operation record for that attempt does not durably reflect that a
  dispatch was ever reported, because this test never reports one -- reporting a dispatch was outside
  this review's own creation-only authorization.

`test_real_stripe_payment_intent_creation_only_against_live_test_mode_api` -- the ONE test in the
suite that makes a real call, `@pytest.mark.skipif`-gated on real credentials actually being
present, run via: `pytest tests/integration/test_stripe_sandbox_operation_lifecycle.py::test_real_stripe_payment_intent_creation_only_against_live_test_mode_api -v` -- **PASSED on its third
invocation** (two earlier invocations failed; see "Test-resource inventory" below for exactly what
each created), after fixing two real bugs this run itself exposed (neither caught by 20 passing
local-simulation tests):

1. **Metadata key length.** `payreality_business_operation_identity_id` (41 characters) exceeds
   Stripe's real, documented 40-character metadata-key limit. The real API's own rejection:
   `{'error': {'message': "Metadata keys can have up to 40 characters, but you passed in a key that
   is 41 characters. Invalid key: payreality_business_operation_identity_id", 'type':
   'invalid_request_error'}}`. `FakeStripeBackend` never validated this at all. Fixed: keys
   shortened with margin (`payreality_biz_operation_identity_id`, `payreality_destination_dispatch_
   id`), plus a new, shared `_validate_stripe_metadata` check Stripe's own length limits, now
   enforced identically by `build_metadata` (fails before any call is attempted, real or simulated),
   `FakeStripeBackend` (so local simulation would now catch this class of bug), and `RealStripeClient`
   (fails locally before spending a real API call).
2. **Metadata stability across a carried-forward key -- a real, load-bearing design flaw, not a
   formatting issue.** The SECOND create call in this test (the "recovery" leg, reusing the SAME key
   via a carried-forward `destination_dispatch_identity`, exactly revision 2's own central design)
   was rejected by Stripe's own REAL idempotency-error check: `"Keys for idempotent requests can
   only be used with the same parameters they were first used with."` The local simulation's own
   parameter-mismatch fingerprint deliberately excluded metadata (reasoned, at the time, that
   metadata legitimately differs per attempt and should never trigger a false mismatch) --
   **confirmed wrong against the real API**: Stripe's own matching compares the FULL request,
   metadata included. `build_metadata` previously included `payreality_operation_id` and
   `payreality_capability_nonce`, both of which differ between the original attempt and a
   replacement BY DESIGN -- meaning the exact "recovery" scenario this whole design exists to make
   safe was itself broken by its own metadata. Fixed: `build_metadata` no longer sends either field
   -- only values that are genuinely stable for the lifetime of a `destination_dispatch_identity`
   (org/integration/business-operation/destination-identity scoping) are ever sent alongside a
   key-bearing request; per-attempt detail (`Operation.id`, capability nonce) stays in PayReality's
   own database, already fully queryable via the `previous_attempt_operation_id` chain. Re-run after
   the fix: the SAME real PaymentIntent id came back from the second create call, proving the
   recovery mechanism actually works against the real API, not merely against its own simulation of
   itself.

All five of this review's own required scenarios ran, against the real API, in the passing run:
1. Normal creation + read-only retrieval -- a real `pi_...` object created, `livemode: false`
   confirmed, then independently re-retrieved.
2-4. Recovery (new capability/attempt, same destination identity, same idempotency identity):
   proven via Stripe's own real idempotency cache, not a simulated one -- the second create call,
   under the carried-forward key, returned the IDENTICAL real PaymentIntent id; no second object
   was created.
5. Read-only recovery after execution authority is revoked: the Agent was revoked, a NEW submission
   was correctly rejected (`IntegrationRejectionError`, before any Decision/Capability was even
   reached), and a real, genuine `retrieve_status` call against the SAME PaymentIntent still
   succeeded -- read-only observation authority confirmed structurally separate from execution
   authority, against the real API.

**Exactly how "response loss" was and was not simulated, stated without conflating the three
distinct mechanisms:**
- **Against the real API (steps 2-4 above): no response loss of any kind was simulated.** Both
  create calls completed with normal, fully-received HTTP responses -- the second call's own request
  was genuinely sent, genuinely processed by Stripe, and its response genuinely received by this
  adapter; Stripe's own server-side idempotency cache is what returned the original object, not a
  recovery from anything lost. What this proves is narrower, and real: that a repeated call under
  the same derived key reliably resolves to the same object via Stripe's own real cache. It does
  NOT prove recovery from an actual lost response, a transport timeout, or a crash, because none of
  those occurred in this run -- there is no mechanism in `RealStripeClient` to inject any of them,
  and none was attempted.
- **In local simulation only** (`FakeStripeBackend.drop_next_response_for_key`, exercised in
  `test_lost_response_after_successful_creation_recovered_via_retry_with_same_key` and
  `test_replacement_authorized_despite_unresolved_outcome_carries_forward_the_same_destination_
  identity`): models specifically **"receiving a successful response and discarding it before
  durable recording"** -- the underlying mutation genuinely executes and its result is cached
  exactly as Stripe documents, but the caller is handed a simulated `TimeoutError` instead of that
  result. This is deliberately NOT a transport timeout (no request is actually lost or delayed) and
  NOT a process crash (nothing about the caller's own process state is disturbed) -- it isolates the
  one specific failure mode this design is built to tolerate. Neither of the other two mechanisms is
  simulated anywhere in this codebase; both remain genuinely untested, locally or externally.

No confirmation, capture, or settlement call was made anywhere in this session -- only
`create_or_resume_payment_intent` and `retrieve_status` were ever called against the real client.
No real customer information was ever sent; only synthetic, PayReality-internal UUIDs as metadata.

### Test-resource inventory

The real test was invoked three times this session. **Established count: 2 real test-mode
PaymentIntent objects created in total, under Stripe account `acct_1UKd2c4JbCzSDIvK`** (the account
id is not sensitive and appears directly in Stripe's own `request_log_url` responses below; reasoned
from the exact pass/fail sequence of the three invocations, not from a list/search call -- none was
made, and none is authorized for this task beyond the test's own already-known objects):

| Invocation | Outcome | Objects created | Why |
|---|---|---|---|
| 1 | FAILED | 0 | Rejected by Stripe at request-validation time (metadata key length, `invalid_request_error`) -- a validation rejection happens before any object is persisted. Captured, real, sanitized evidence: `status=400`, `request_log_url=https://dashboard.stripe.com/acct_1UKd2c4JbCzSDIvK/test/workbench/logs?object=req_qjYqptCfMBvLfL`. |
| 2 | FAILED | 1 | The first create call (operation A) succeeded -- the failure happened on the SECOND create call (operation B's recovery leg), which Stripe rejected with a real `idempotency_error` (the metadata-stability bug, see above) -- a rejection, not a second creation. Captured, real, sanitized evidence for the FAILING second call: `status=400`, `request_log_url=https://dashboard.stripe.com/acct_1UKd2c4JbCzSDIvK/test/workbench/logs?object=req_Rg4Tjys4QTfl3k`, derived idempotency key prefix `1384caad-66e9-48b7-a477-2ce392c9e1e9:...` (synthetic UUIDs only, no secret). The FIRST (successful) call's own object id and request id were never printed by the test and are not recoverable from any artifact this session retained. |
| 3 | PASSED | 1 (operation A's create; operation B's recovery call resolved to the SAME object, confirmed equal by the test's own assertion, not a new creation) | This is the final, passing run reported above. Its own object id and request id were likewise never printed (pytest suppresses stdout on a passing test by default, and the test contains no print statements) and are not recoverable from any retained artifact. |

**Total: 2 real objects.** The intended recovery pair (invocation 3, operation A + operation B) is
confirmed to be exactly ONE object, not two, by the test's own passing assertion (`created_b["id"]
== created_a["id"]`). The additional object is the orphaned, never-reused object from invocation 2's
own operation A, created under that invocation's own (now-discarded) organization id, before that
run failed on its own second call.

**Why no further retrieval was attempted**: this review's own evidence request authorizes read-only
retrieval of "the task's own known objects only." The two object ids that actually exist (from
invocations 2 and 3) were never captured in any log, print statement, or saved artifact -- only
their REQUEST ids (not object ids) for the two FAILING calls are known, and a request id is not
retrievable the same way an object id is. Reconstructing either object's id would require either (a)
a list/search call against the account (not authorized -- this review explicitly excludes searching
for objects beyond what is already known), or (b) re-running the test again, which would create a
THIRD object (not authorized -- this review explicitly excludes creating new objects). Both are
withheld. No claim is made about the account's contents beyond these two specific, reasoned-about
objects; nothing here establishes or implies an absence of other PaymentIntents on this account.

All created objects: test-mode (`livemode: false`, confirmed by the passing run's own assertion),
`status: requires_payment_method` throughout (never confirmed, never captured), no real money
involved, no cost. Left as-is -- Stripe provides no delete operation for a PaymentIntent, and
test-mode data carries no retention concern, so no cleanup action exists to take or is needed.

### Remaining unverified behavior

Everything this review's own narrow authorization did NOT cover, still genuinely unverified against
the real API:

- PaymentIntent **confirmation** (a test card actually being charged in test mode), **decline**
  handling, **requires_action** (3-D Secure-style) handling -- `confirm_payment_intent_if_pending`
  has never been called against `RealStripeClient` at all.
- The expired-window guard (`DispatchWindowExpiredError`) and the account-binding mismatch check
  (`StripeAccountBindingMismatchError`) -- not merely "untested against adverse conditions," but
  **structurally never invoked against the real API at all** this session, because the real test
  calls `create_or_resume_payment_intent` directly rather than the full `dispatch_payment_intent`
  orchestration those two checks live inside (see "External execution" above for why: the full
  orchestration would also attempt a confirm call, outside creation-only scope). Both remain
  verified only against `FakeStripeBackend`.
- The restricted key's own granted-permissions boundary: this session's `rk_test_` key evidently had
  PaymentIntent create/read access; a differently-scoped restricted key could still fail with a real
  Stripe authorization error this adapter has never exercised.
- The real HTTP/ASGI submission API, its routing, and its request-authentication middleware --
  every test in this file, including the real-API one, calls PayReality's own service-layer
  functions directly, never through an actual HTTP request (a pre-existing, disclosed, repository-
  wide convention, not something this session changed).
- The observation/reconciliation loop for a real dispatch: no test in this file ever feeds a real
  Stripe PaymentIntent's own outcome back into PayReality via `record_dispatch_evidence`/
  `record_observation`/reconciliation -- `outcome_status` for every Operation touched by the real
  test stays `UNKNOWN` throughout, exactly as it does in the FakeStripeBackend-based tests that
  likewise never call these functions.

None of these are described as proven; all remain exactly as disclosed, or disclosed more precisely
than before this session -- outstanding, not completed.

**What "20 (local) + 1 (real)" means, precisely**: the 20 LOCAL tests run against `FakeStripeBackend`
(or, for some, a plain Python object implementing only the read-only method, or no I/O at all) --
proof that this adapter's own orchestration logic is correct, not proof that real Stripe test mode
behaves as documented; two places that proof turned out to be wrong were found and fixed only once
the 21st, real test actually ran (see "External execution" above). The retention/parameter-matching/
concurrency facts the simulation models are each cited to Stripe's own official documentation (see
"Official sources" below). The dispatch-window concurrency claim specifically is proven separately,
against a real Postgres database (not SQLite -- see "Dispatch window anchoring" below for why), as a
standalone script, not as a pytest case.

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
  still_valid` blocks a dispatch attempt outright once this module's own conservative 24h boundary
  has elapsed since the *real first dispatch* for this #4 chain (see the next section for why "real
  first dispatch," not issuance), if the outcome is still unresolved -- rather than silently
  dispatching under cover of a key Stripe itself may or may not still hold. Longer-term,
  business-level protection against re-attempting a *resolved* operation remains
  `evaluate_replacement_safety`'s job, unchanged, layered underneath this guard.

## Dispatch window anchoring and Stripe account binding (revision 3)

Two further gaps, found and fixed in this pass, in how the revision-2 design above was actually
*anchored* and *scoped* -- neither is a flaw in the identity mapping itself, both are flaws in what
feeds it.

### The window must be anchored to the real first dispatch, not capability issuance

`ensure_dispatch_window_still_valid`'s own 24h-conservative boundary is only meaningful if measured
from the moment Stripe's own idempotency key was actually first created -- i.e. the real first
dispatch attempt. The adapter itself is deliberately DB/ORM-free (see its own module docstring), so
it has never stored this timestamp itself; a caller supplies it. The first version of this design
used `Operation.created_at` (the ROOT operation's own row-creation time) as a disclosed proxy. This
is wrong in one direction and, if a caller's own data model differed, could be wrong in the other
too: `Operation.created_at` is set at `capability_service.issue_capability_for_decision`'s own
`create_operation_for_decision` call -- i.e. at *authorization/issuance* time, which precedes the
Agent actually consuming the Capability (`record_claim`) and, separately again, actually calling
the destination. A real gap between issuance and dispatch (an Agent holding a consumed Capability
briefly before acting, a queued dispatch, anything short of perfectly synchronous execution) means
measuring from `created_at` anchors the window to *capability issuance*, not *first dispatch* --
exactly the wrong anchor this review's own task explicitly calls out.

**Fixed**: a new, durable, set-once table, `stripe_sandbox_dispatch_windows`
(`app/db/stripe_sandbox_models.py`, migration `b8e1f4d6a2c7`), one row per `destination_dispatch_
identity`, written exactly once -- at the real moment a caller first attempts to dispatch for that
identity -- via `app/services/stripe_sandbox_dispatch_window_service.get_or_record_dispatch_window`.
A second call for an identity that already has a row (a genuine retry, a replacement that carries
the same identity forward via the chain-walk, or a genuinely concurrent racer) reads back exactly
what the first caller recorded; its own `attempted_at` is silently ignored. This is a SEPARATE
table from `operations`, not a new column on it -- see that module's own docstring for why (this
session's own working directory already carries unrelated, uncommitted changes to `models.py` from
a different in-progress branch; a separate table avoids touching that file at all, a real
constraint of this specific working environment, not a general design preference).

**Race safety, proven against a real Postgres database, not asserted or merely tested against
SQLite**: `get_or_record_dispatch_window`'s set-once guarantee rests on the row's own primary-key
uniqueness constraint (pre-check, insert, catch the loser's `IntegrityError`, re-read the winner's
row) -- the same pattern this codebase already established for
`create_operation_for_decision`/`resolve_or_create_business_operation_identity`. This could not be
proven as a genuine multi-thread race against this test suite's own SQLite in-memory `db` fixture:
SQLAlchemy's `SingletonThreadPool` gives each THREAD its own private, isolated `:memory:` database
(confirmed directly this session -- a second thread's connection could not even see a table the
first thread had just created), so two threads racing against that fixture would each be racing
against their OWN, separate, empty database, proving nothing. Proven instead as a standalone script
against a real, throwaway Postgres container: two real threads, each its own SQLAlchemy session
bound to one real Postgres engine (which has no such per-thread isolation), synchronized on a
`threading.Barrier` to maximize actual overlap, both racing `get_or_record_dispatch_window` for the
identical `destination_dispatch_identity` -- exactly one row persisted, the losing thread read back
the winning thread's own `(attempted_at, account_id)` unchanged. See this review's own final report
for the exact command and output.

**24 hours is a conservative lower bound, never an exact deletion time** -- corrected throughout
this module's own docstrings this pass. Stripe's own documentation says a key may be removed "after
they're at least 24 hours old," which guarantees survival for at least that long but promises
nothing about exactly when (or whether) pruning happens afterward. `STRIPE_IDEMPOTENCY_KEY_
RETENTION_HOURS` is used as the EARLIEST point pruning becomes possible, and this module stops
relying on the key from exactly that point forward -- not because pruning is assumed to have
happened, but because it can no longer be ruled out either way.

### Account scoping: resolving, binding, and rejecting a mismatch

Embedding `organization_id`/`integration_id` directly in the idempotency key (revision 2) is **not
sufficient on its own**, per this review's own explicit finding: Stripe scopes idempotency keys
*per Stripe account*. Reusing the same key string against a *different* account does not collide at
all -- there is nothing there to collide with -- it silently creates an independent, unrelated
object, defeating the entire point of carrying a destination identity forward across a replacement.
A rotated credential (the integration's configured `STRIPE_TEST_SECRET_KEY` changed to point at a
different Stripe account, without anything about `integration_id` itself changing) could otherwise
silently redirect what was meant to be a resumption of operation A's own in-flight dispatch into a
brand-new, independent object on a completely different account.

**Fixed**: `dispatch_payment_intent` now resolves the Stripe account the *currently configured*
credential actually belongs to, on every call, via `client.retrieve_account()` -- Stripe's own `GET
/v1/account` (the account associated with the API key used, confirmed via Stripe's own SDKs; e.g.
`stripe.Account.retrieve()` with no id resolves to this exact endpoint -- distinct from `GET
/v1/accounts/{id}`, which looks up an already-known Connect-managed account). This is compared
against `bound_stripe_account_id`, the account recorded in `stripe_sandbox_dispatch_windows` at
this destination identity's own first dispatch; a mismatch raises `StripeAccountBindingMismatchError`
and refuses to dispatch, *before* any create/confirm call is attempted. The binding itself is
set-once, by the same race-safe mechanism as the timestamp above (same table, same function, same
proof).

**Live-mode rejection, structural and independent of the existing credential-prefix check**: every
PaymentIntent object this module touches (create, confirm, retrieve) is checked for
`livemode == true` (`docs.stripe.com/api/payment_intents/object`: "If the object exists in live
mode, the value is `true`. If the object exists in test mode, the value is `false`.") and rejected
outright (`LiveModeObjectRejectedError`) if it ever is -- defense in depth alongside, not instead
of, `RealStripeClient.__init__`'s own refusal to construct with anything other than an `sk_test_`
key. The Account object itself has no documented `livemode` field (confirmed via
`docs.stripe.com/api/accounts/object`), so mode enforcement stays at the credential-prefix and
PaymentIntent-object layers, not duplicated at the account layer where it would not apply.

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
- [The PaymentIntent object](https://docs.stripe.com/api/payment_intents/object) -- confirmed the
  `livemode` (boolean) field and its exact meaning, grounding this revision's structural live-mode
  rejection.
- [The Account object](https://docs.stripe.com/api/accounts/object) -- confirmed `id` as the
  account's own unique identifier and the absence of a `livemode` field on this object (mode
  enforcement stays at the credential-prefix and PaymentIntent-object layers instead). `GET
  /v1/account` (the account associated with the current API key, no id required) is confirmed via
  Stripe's own SDK behavior (`Account.retrieve()` with no argument resolves to this endpoint, per
  Stripe's own `stripe-node`/`stripe-python` documentation and maintainer discussion) rather than a
  single, separately browsable reference page at the current docs.stripe.com structure, which now
  documents the Connect-oriented `GET /v1/accounts/{id}` form most prominently.

## Explicitly not done by this plan or its implementation

**No live payment executed, no confirmation/capture call made, no real customer information ever
sent, no live-mode object or credential ever accepted.** A real, test-mode-only PaymentIntent
CREATION call now has run (see "External execution: what actually ran" above) -- narrower claims
from earlier in this document's own history ("no real Stripe API call made") are superseded by
that section, not still true; this line is corrected here so the two are never left to
contradict each other. Still genuinely not done: PaymentIntent confirmation, decline/3-D-Secure
handling, and every item listed under "Remaining unverified behavior" above.
