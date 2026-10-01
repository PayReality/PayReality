# EvidenceBound / PayReality Comparison Package

`interop_id: EVIDENCEBOUND-PAYREALITY-RECOVERY-V01`
`operation_id: EVIDENCEBOUND-PAYREALITY-RECOVERY-V01-OP-001`

This package is the sanitized output of PayReality's own consolidation review of the operation
lifecycle feature (`OPERATION_LIFECYCLE.md`), verified against real code and a real test harness,
not asserted from a design document. These traces were generated against real PayReality code
using SQLite and a synthetic destination. Postgres verification was performed separately (see
"Database engines" below for exactly what that separate verification covered, and what it did not
touch). None of the traces in `traces/` are hand-written or simulated.

## The shared vector

Every schedule below shares the same frozen order:

| Field | Value |
|---|---|
| Action | `purchase_order_create` |
| Supplier | `supplier:A` |
| Quantity | `120` |
| Buyer account | `ACCT-B` |
| Delivery location | `location:X` |
| Unit price | `42.50` (fixed) |
| Source operation | `EVIDENCEBOUND/v1.SubmitOrder` |

Holding this vector fixed across schedules is deliberate: any observed difference between
schedules is attributable to the scenario (revocation timing, concurrency, a changed field) being
varied, not to a different order being described.

## Schedules

| File | Scenario | What it shows |
|---|---|---|
| `traces/schedule_1_late_commitment_after_revocation.jsonl` | **Two separate experiments, sharing this one file because both are tagged `schedule: "1"`** -- distinguished by their own `external_operation_id` field (added this pass so the split is evident directly from the data, not just from prose): (a) records 1-9, `external_operation_id` ending `-OP-001` -- a destination commits the order internally without issuing a receipt; execution authority (the origin Agent) is revoked; the destination is later queried and reports `COMMITTED`; a signed Adapter observation is still recordable (observation authority is separate from execution authority) and reconciliation reaches `MATCHED`. (b) records 10-11, a SEPARATE Decision/Operation, `external_operation_id` ending `-OP-001-IDENTITY-CHECK` -- tests revoking the *IntegrationIdentity* instead of the Agent; this second operation's own observation is blocked and never recorded, so it stays `RECEIPT_MISSING` -- not a reversal of (a)'s own `MATCHED` conclusion, a different operation entirely that never reached it. | (a) PayReality can still record and reconcile a late, authenticated observation even after the acting Agent's own execution authority is gone -- because observation and execution are two separate authorities, not one. (b) Revoking the *reporting* identity (not the acting Agent) blocks a late observation that execution-authority revocation alone did not -- the two are genuinely independent controls, proven by a second, separate experiment, not implied by the first. |
| `traces/schedule_2_unresolved_outcome_after_revocation.jsonl` | The destination is queried and returns an ambiguous `NOT_FOUND_NOW` (not authoritative); execution authority is revoked; reconciliation is left `RECEIPT_MISSING`/unresolved; a fresh attempt by the *same* revoked Agent is denied outright; a fresh attempt by a *different*, active Agent is granted authorization but explicitly **not** established as safe. **Why not established, precisely** (record 6's own field, corrected this pass): not because no replacement-safety mechanism exists in PayReality -- it does (`operation_service.evaluate_replacement_safety`), and is exercised elsewhere in this same codebase -- but because this schedule's own Integration Contract Version defaults to `lifecycle_requirement=LEGACY` and its own Intent never supplies `business_operation_id`, so that real mechanism is never invoked for this specific, deliberately minimal submission path. See `CONTRACT_VS_OBSERVED_MATRIX.md` row 12 for the mechanism's own real, platform-wide scope. | Unresolved outcome after revocation: PayReality does not, and does not claim to, resolve an ambiguous outcome on its own, and does not claim a fresh attempt is safe merely because a new Agent is authorized to make it -- and this schedule's own configuration is a genuine example of a submission path the mandatory protection does not reach, not evidence the protection doesn't exist. |
| `traces/material_action_binding_enforcement.jsonl` | Four declared-material fields (`supplier`, `quantity`, `buyer_account`, `delivery_location`) are each independently changed and rejected; `unit_price`, undeclared in this Integration Contract Version's own `context_bindings`, is silently unenforced if omitted from the original request but rejected outright if explicitly submitted. | Exactly what "material" means here: whatever a specific Integration Contract Version actually declares, not a fixed, universal list PayReality enforces on every integration's behalf. |
| `traces/capability_consumption_concurrency.jsonl` | Two independent OS processes, real file-backed SQLite, race to consume the same already-issued Capability at the same instant. | Capability-consumption concurrency: exactly one connection succeeds; the loser gets a real, typed rejection (`CapabilityTokenAlreadyConsumedError`), not a silent double-spend. |
| `traces/operation_attempt_registration_concurrency.jsonl` | Two independent OS processes (`multiprocessing`, not threads) submit separate Intents for the same, brand-new `business_operation_id` at the same instant. | Operation/attempt-registration concurrency -- a genuinely different race from capability consumption above (registering the *first* attempt at a business-operation identity, not consuming an already-issued token): exactly one process wins and is issued a real Capability; the other is blocked by replacement-safety (`UNSAFE_UNRESOLVED`), not silently allowed to also proceed. |

## Reading the traces

**Provenance, stated precisely**: every fact in these five trace files comes from one of exactly
two sources -- real PayReality service code (never mocked), or this test harness's own synthetic
destination (`FakeDestination`, standing in for a real external system, since PayReality has no
destination-interaction code of its own to exercise -- see `REPRODUCTION.md`/the generating test
file's own "Destination interaction: NONE" note). All five files were captured against SQLite (see
"Database engines" below for exactly which mode); a separate, real PostgreSQL verification exists
for the broader feature but is not reflected in any record here.

Most, but **not every**, record carries an `evidence_source` field stating plainly where that
specific fact came from -- confirmed directly against the regenerated files, not assumed: a
handful of simple structural records (e.g. `execution_authority_revoked`, `no_auto_retry_no_
release`) omit it, where the event name itself already states the source unambiguously. Where
present, `evidence_source` follows two conventions:

- `payreality_*` -- a real PayReality service function's own return value or persisted state.
- `synthetic_destination*` -- the test harness's own fake destination. **Labeled explicitly**
  wherever it appears; never presented as if it were a real destination's own record.
- Any field or event explicitly noting `(test harness ground truth, NOT obtainable by PayReality)`
  is exactly that: something the test asserts as true for the purpose of checking PayReality's own
  behavior against it, not something PayReality itself ever claims to know.

`effect_count` is `"UNKNOWN"` wherever the trace does not establish a specific, confirmed count --
never fabricated to look more precise than the evidence supports.

## Database engines

- `capability_consumption_concurrency.jsonl`, `operation_attempt_registration_concurrency.jsonl`:
  SQLite, file-backed (not in-memory), across two real, independent OS processes -- the file backing
  is what makes the race real across process boundaries; an in-memory SQLite database is
  per-process and cannot exhibit this race at all.
- `schedule_1_*`, `schedule_2_*`, `material_action_binding_enforcement.jsonl`: SQLite, in-memory,
  single process (these schedules are sequential, not concurrent, so no cross-process backing is
  needed).
- **Separate from these five files entirely**: the full migration chain and the broader lifecycle
  test suite were also verified against real PostgreSQL (see `REPRODUCTION.md`) -- a genuinely
  different verification pass, run against different test files, producing no records that appear
  in `traces/` here. Stated plainly so the two are never conflated: nothing in this package's own
  trace data was ever captured against Postgres.

## Contents of this package

- `README.md` -- this file.
- `traces/` -- the five sanitized trace files described above.
- `CONTRACT_VS_OBSERVED_MATRIX.md` -- what PayReality's own architecture claims, next to what was
  actually observed running real code, for each claim.
- `REPRODUCTION.md` -- exact commands and environment requirements to regenerate every trace here.
- `DRAFT_MESSAGE_TO_RUSLAN.md` -- a short draft message. Not sent; prepared for the user's own
  review and decision.

## What is deliberately NOT in this package

Credentials, personal information, internal endpoints/URLs, raw sensitive logs, and any detail of
this repository unrelated to the lifecycle feature under comparison. Every identifier in the traces
(agent IDs, capability IDs, identity IDs) is an ephemeral UUID generated fresh by the test harness
that produced it -- not a real customer, real credential, or real production identifier.
