# Authority Intelligence Program — Phase 5: Runtime Policy Lifecycle & Enterprise Runtime Management — Summary

**Principle:** Build strictly on top of the existing Policy Studio architecture (Phases 1-4 unmodified). Reuse existing validation, the existing Diff engine, the existing Approval Audit pattern, and existing RBAC permissions. No new architecture, no new statuses beyond one, no background task runner.

---

## What it is

Runtime Policies gain a real lifecycle on top of the existing draft → pending_review → approved → compiled → active → retired pipeline (all seven of those transitions are completely unmodified): explicit versioning with rollback, scheduled activation and retirement, a Runtime Impact Preview and Runtime Authority Safety Check gate before activation, a Policy Timeline that doubles as the Enterprise Audit trail, and a cross-policy Dashboard/Search surface. Every new capability is additive — nothing in Phases 1-4 changed behavior, signature, or return type.

## How it's built — composition, not new logic

| Piece | Status |
|---|---|
| `runtime_policy_service.create_policy/edit_policy/submit_for_review/approve/reject/compile_policy` | **Reused unchanged**, each now ends with one defensive, best-effort `record_lifecycle_event()` call — never touches the transition's own logic, return type, or exception behavior. |
| `runtime_policy_service.deploy_policy` | **Reused unchanged, zero instrumentation added directly.** It has no `actor`/`reason` parameters to record anything meaningful with; the new `activate_policy()` wrapper calls it and records its own, richer `activated` event afterward instead. |
| `runtime_policy_service.diff_versions` / `compute_condition_diff` | **Reused unchanged** for the Runtime Impact Preview — no separate diff logic was written. |
| `runtime_policy_service.reconcile_opa_with_active_policies` | **Reused unchanged** by the one genuinely new transition, `retire_policy()`, to push the remaining active set to OPA after removing one policy with no replacement — no bundle-compilation logic was duplicated. |
| `ai_authority_builder_service.detect_circular_delegations` | **Reused unchanged.** The new safety check builds synthetic `CandidateRelationship` values from `Constraints.delegated_by` chains and hands them to the exact same Phase 3 cycle-detection function; it has no idea these came from RuntimePolicy rather than a corpus. |
| `runtime_policy.validators.validate` | **Reused unchanged** for the "invalid thresholds" safety check. |
| `domain/evidence/signing.payload_hash` | **Reused unchanged** for hashing every lifecycle event, the same precedent Phase 3's `AuthorityGraphApproval.graph_hash` established. |
| RBAC (`Permission.RUNTIME_POLICY_PUBLISH`, `Permission.RUNTIME_POLICY_EDIT`, `Permission.AUTHORITY_REVIEW`) | **Reused unchanged.** No new `Permission` enum values. |
| `services/runtime_policy_safety_checks.py` | **New.** Duplicate-authority, broken-inheritance, and missing-principal checks — narrow, deterministic, no existing equivalent to reuse. |
| `services/runtime_policy_lifecycle_service.py` | **New.** All orchestration: activation, scheduling, rollback, retirement, deprecation, archival, timeline, search, dashboard. |
| `RuntimePolicyLifecycleEvent` / `PolicyActivationSchedule` tables | **New.** |

## Design decisions and why

- **Exactly one new stored status: `archived`.** Widened the existing CHECK constraint from 7 to 8 values; every prior status string remains valid.
- **"Superseded" is a read-side label, not a status.** A `retired` row with a newer `active` sibling of the same `policy_key` is presented as "Superseded" by `effective_status()`, computed on every read — this avoids touching `deploy_policy`'s already-working "prior version → retired" transition at all.
- **"Deprecated" is a flag on an ACTIVE row (`deprecated_at`/`deprecation_reason`), never a status change.** `_other_active_policies` and `reconcile_opa_with_active_policies` both filter on the literal string `status == "active"`; changing status away from "active" would immediately stop enforcement, which contradicts "deprecated but still scheduled for future retirement."
- **Scheduling is a separate table (`PolicyActivationSchedule`), not a status.** A "scheduled" policy is still `approved`/`compiled` right up until its schedule executes — there is no in-between status to invent.
- **`retire_policy()` is the one genuinely new transition.** Every other Phase 5 mutation composes existing functions; retiring an active policy with no replacement has no existing equivalent (`deploy_policy` only ever retires the prior version of the *same* policy when a *new* version of it activates), so this one small function (flip status, reuse `reconcile_opa_with_active_policies`) is new. Added `retired` as an eighth allowed `event_type` on the lifecycle-events CHECK constraint to record it (this migration was never applied anywhere before this phase, so it was edited directly rather than layering a second migration on top).
- **`Approve`/`Reject` stay on `Permission.AUTHORITY_REVIEW`, not moved to `Permission.RUNTIME_POLICY_PUBLISH`.** The Phase 5 prompt's "only Policy Administrators may Approve" would change existing, working RBAC behavior (`Role.REVIEWER` already holds `AUTHORITY_REVIEW` and already approves/rejects Runtime Policies as of Phase 10) — moving it now is a scope change this phase doesn't make. `Activate`/`Schedule`/`Rollback`/`Retire`/`Archive`/`Deprecate` — every genuinely new action — gate on `Permission.RUNTIME_POLICY_PUBLISH`, held only by `Role.GOVERNANCE_ADMIN` and `Role.OWNER`, which is this platform's actual "Policy Administrator" equivalent.
- **Rollback creates a new DRAFT version and does not skip the review pipeline.** `rollback_policy()` copies a previous version's content into a new draft (tagged `rollback_of_version`), then requires the normal submit → approve → compile → activate sequence like any other change. History remains append-only; nothing is reactivated directly.
- **The frontend's "Publish" button on `PublishPage` now calls the new safety-gated `lifecycle/activate` endpoint instead of the old raw `/deploy` endpoint.** This is the one place existing UI *behavior* changes: `deploy_policy()` itself is completely untouched and still directly callable, but the product surface that publishes now actually runs the new safety gate — otherwise Requirement 6 ("activation must be blocked...") would be unreachable from the product. A publish that would have succeeded before still succeeds unless a genuine new safety violation is present.

## Testing

**264/264 backend tests passing (27 new), zero regressions** against the pre-Phase-5 baseline of 237.

- 16 new pure/fake-session unit tests for `runtime_policy_safety_checks.py` (duplicate authority, circular delegation reuse, invalid thresholds, missing principal, broken inheritance — including two tests that assert the fake session's `db` is never even queried on the paths that don't need it).
- 11 new unit tests for `runtime_policy_lifecycle_service.py`: `effective_status`'s superseded/retired distinction, `search_policies`' in-Python filtering, `process_due_schedules`' control flow (including that one schedule failing doesn't abort the batch), and `ActivationBlockedError`'s message formatting.
- Both migration directions (`upgrade`/`downgrade`) re-verified with `alembic ... --sql` after the `retired` event-type addition.
- The full FastAPI app was imported and its OpenAPI schema force-generated (`app.openapi()`) to confirm all 14 new endpoints resolve with no route or schema conflicts.
- Frontend: `npm run build` verified clean.

## Known limitations (disclosed, not glossed over)

1. **No live database or OPA verification was performed for any new lifecycle orchestration function** (`activate_policy`, `rollback_policy`, `retire_policy`, `schedule_activation`, `process_due_schedules`, the dashboard/search queries). Local Postgres is unreachable in this dev environment (confirmed via `OperationalError: connection timeout expired`, the same recurring limitation as Phases 3 and 4). Migrations were verified offline (`alembic ... --sql`, both directions); the orchestration logic itself was verified only by code review, type-checking-free unit tests on its pure sub-pieces, and a clean import/OpenAPI-generation pass — consistent with this codebase's own established convention that DB-dependent orchestration (e.g. `compile_policy`/`deploy_policy` themselves) is verified against a real deployed instance, not faked in a unit test.
2. **`process_due_schedules` is not a background job.** There is no task runner anywhere in this platform. It must be invoked manually or by an external trigger (a cron job, a CI step, an operator action) — nothing calls it automatically. This is the same honest limitation the schema's own docstring states.
3. **`search_policies` is in-Python filtering over every version's JSONB `content`, not a database-level search.** Fine at this platform's current scale; there is no existing JSONB-query helper in this codebase to reuse, and building a real search index was out of scope for this phase.
4. **No TypeScript compiler exists in this project** (confirmed again this phase: no `tsconfig.json`, no `node_modules/.bin/tsc`). Frontend changes were verified via a clean `npm run build` (catches syntax/import errors) and manual review, not real type-checking.
5. **New lifecycle UI pages are not wired into the public demo's mock router** (`src/app/demo/mockRouter.ts`). If the demo build (`VITE_PUBLIC_DEMO_MODE=true`) is ever used to showcase Policy Studio, the new Dashboard/Search page and the Publish page's Activation Preview would hit unmocked endpoints and fail. This is a separate, pre-existing system this phase did not touch.
6. **`rollback_policy`'s target-version guard is a simple check (`activated_at is not None` or `status == "active"`), not a full historical audit.** It correctly rejects rolling back to a version that was never activated, but does not distinguish "retired because superseded" from "retired via `retire_policy` with nothing replacing it" — both are valid rollback targets, which is intentional (either was genuinely active at some point).
7. **No browser-based manual testing was performed.** Verification is limited to the production build succeeding and manual code review of every new component against this codebase's existing design-token/component conventions.

## Security review (self-directed, matching this program's own established practice)

- **No evidence leakage / no signing-key reuse**: every new hash uses `payload_hash()` (a hash, never a signature) — no lifecycle event or schedule row is ever signed with the real Evidence key.
- **No cross-policy contamination**: `run_safety_checks` reads only the candidate row and other currently-*active* rows; it never reads or is influenced by draft/pending content belonging to a different reviewer's unrelated work.
- **Activation cannot silently bypass the safety gate**: both `activate_policy` and `schedule_activation` run `run_safety_checks` before calling `compile_policy`/`deploy_policy` or writing a schedule; a blocked attempt is itself recorded as an immutable `activation_blocked` event, not silently dropped.
- **Archived policies are immutable**: `edit_policy` now raises `InvalidTransitionError` if the latest version's status is `archived`, closing the one path that could otherwise mutate an archived policy's lineage.
- **Permission boundaries respected**: every genuinely new mutating endpoint requires `Permission.RUNTIME_POLICY_PUBLISH`; every read endpoint carries no permission dependency, matching the existing `runtime_policies.py` router's own convention for reads.

## Honest assessment of production readiness

The domain design (state model, safety-check gating, audit trail, RBAC mapping) is sound and directly composes proven Phase 1-4 machinery rather than inventing parallel logic. The backend's pure and single-query logic is genuinely unit-tested; the multi-step orchestration (the actual activate/rollback/retire/schedule flows end-to-end against a real Postgres and a real OPA instance) has **not** been exercised in this session and should be before this ships to any environment carrying real traffic — the same gap this program has disclosed at every prior phase where a live database was unreachable. The frontend is additive, uses existing design tokens throughout, and builds clean, but has not been exercised in a browser. **Do not treat this phase as verified end-to-end; treat it as code-reviewed, unit-tested where feasible, and ready for live-database verification before production use.**
