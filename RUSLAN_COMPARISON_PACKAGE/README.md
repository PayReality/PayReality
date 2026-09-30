# EvidenceBound / PayReality Comparison Package

`interop_id: EVIDENCEBOUND-PAYREALITY-RECOVERY-V01`
`operation_id: EVIDENCEBOUND-PAYREALITY-RECOVERY-V01-OP-001`

This package is the sanitized output of PayReality's own consolidation review of the operation
lifecycle feature (`OPERATION_LIFECYCLE.md`), verified against real code and a real test harness,
not asserted from a design document. Every trace in `traces/` was produced by actually running the
named test against real application code (SQLite or Postgres, never mocked) in this session; none
are hand-written or simulated.

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
| `traces/schedule_1_late_commitment_after_revocation.jsonl` | A destination commits the order internally without issuing a receipt; execution authority (the origin Agent) is revoked; the destination is later queried and reports `COMMITTED`; a signed Adapter observation is still recordable (observation authority is separate from execution authority) and reconciliation reports `MATCHED`. | Late-reported commitment after revocation: PayReality can still record and reconcile a late, authenticated observation even after the acting Agent's own execution authority is gone -- because observation and execution are two separate authorities, not one. |
| `traces/schedule_2_unresolved_outcome_after_revocation.jsonl` | The destination is queried and returns an ambiguous `NOT_FOUND_NOW` (not authoritative); execution authority is revoked; reconciliation is left `RECEIPT_MISSING`/unresolved; a fresh attempt by the *same* revoked Agent is denied outright; a fresh attempt by a *different*, active Agent is granted authorization but explicitly **not** established as safe (no duplicate-prevention mechanism exists to evaluate it). | Unresolved outcome after revocation: PayReality does not, and does not claim to, resolve an ambiguous outcome on its own, and does not claim a fresh attempt is safe merely because a new Agent is authorized to make it. |
| `traces/material_action_binding_enforcement.jsonl` | Four declared-material fields (`supplier`, `quantity`, `buyer_account`, `delivery_location`) are each independently changed and rejected; `unit_price`, undeclared in this Integration Contract Version's own `context_bindings`, is silently unenforced if omitted from the original request but rejected outright if explicitly submitted. | Exactly what "material" means here: whatever a specific Integration Contract Version actually declares, not a fixed, universal list PayReality enforces on every integration's behalf. |
| `traces/capability_consumption_concurrency.jsonl` | Two independent OS processes, real file-backed SQLite, race to consume the same already-issued Capability at the same instant. | Capability-consumption concurrency: exactly one connection succeeds; the loser gets a real, typed rejection (`CapabilityTokenAlreadyConsumedError`), not a silent double-spend. |
| `traces/operation_attempt_registration_concurrency.jsonl` | Two independent OS processes (`multiprocessing`, not threads) submit separate Intents for the same, brand-new `business_operation_id` at the same instant. | Operation/attempt-registration concurrency -- a genuinely different race from capability consumption above (registering the *first* attempt at a business-operation identity, not consuming an already-issued token): exactly one process wins and is issued a real Capability; the other is blocked by replacement-safety (`UNSAFE_UNRESOLVED`), not silently allowed to also proceed. |

## Reading the traces

Every record carries `evidence_source`, stating plainly where that specific fact came from:

- `payreality_*` -- a real PayReality service function's own return value or persisted state.
- `synthetic_destination*` -- the test harness's own fake destination, standing in for a real
  external system. **Labeled explicitly** wherever it appears; never presented as if it were a real
  destination's own record.
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
- Separately, the full migration chain and the broader lifecycle test suite were also verified
  against real PostgreSQL (see `REPRODUCTION.md`) -- not reflected in these specific trace files,
  which predate that distinction and were captured against SQLite as the test files' own default.

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
