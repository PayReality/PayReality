# Part 24 — Phase 1 (Runtime Core): Plan, Risk Assessment, Conformance Checklist, Roadmap

**Status:** planning, pre-implementation. **Baseline:** [23_RUNTIME_GOVERNANCE_MIGRATION_BASELINE.md](23_RUNTIME_GOVERNANCE_MIGRATION_BASELINE.md), commit `eb54f3e`. **Scope:** Policy Intelligence completion, Runtime Authority verification, Decision Evidence completion, six-role provenance, explicit Policy Version recording, documentation drift correction.

## 24.1 What Phase 1 does NOT need to do

Per the baseline's §23.1 and §23.4.1 corrections, two of the six original Phase 1 items are already closed:

- **Two-writer elimination**: already done, committed, verified (`domain/compiler/` doesn't exist; `routers/policies.py`'s four write endpoints already `410`). Moved to Phase 2 as a declaration task, not a fix.
- **Context persistence**: already done, committed, verified (`authority_context` is already written into `Evidence.payload`).

This narrows Phase 1 to four real items, each grounded in specific, read code — not assumed gaps.

## 24.2 Implementation plan

### 24.2.1 Explicit Policy Version and Authority Version recording

**Current state, verified**: `decision/engine.py::evaluate()` already resolves `active_policy.version` and threads it into `build_opa_input()` (so OPA itself sees it) — but neither `Decision` nor `Evidence` captures it directly. Today, "which policy version governed this decision" is reconstructable only via `Decision.policy_id` → a join against the `policies` table, which happens to still hold the row (retained, not deleted, per §17.4) — correct today, but indirect, and dependent on that row never being purged.

There is no "Authority Version" concept anywhere in this codebase — `decision/engine.py` has no version identifier for its own evaluation logic, unlike the compiler (`COMPILER_VERSION = "2.0.0"`, an existing, precedented pattern).

**Change**:
1. Add a `DECISION_ENGINE_VERSION` constant to `domain/decision/engine.py`, mirroring `bundle_builder.py`'s `COMPILER_VERSION` pattern exactly — same shape, same rationale, so the codebase gains one more instance of a pattern it already trusts rather than a new one.
2. Add `policy_version` (int, from `active_policy.version`) and `policy_bundle_hash` (str, from the `Policy` row's existing `bundle_hash` column) to the `Decision` dataclass in `engine.py`, and thread both into `intent_service.py`'s `Decision` and `Evidence` construction.
3. Add `authority_version` (the new `DECISION_ENGINE_VERSION` constant) to the Evidence payload.

All three are additive fields on `payload_version: 2` — no version bump, no branching required of any existing reader, per this codebase's own established convention (§16.3's comment in `_build_evidence_payload`: "additive... not a new payload shape a verifier needs to branch on").

### 24.2.2 Six-role provenance

**Current state, verified**: `agent_id` (who asserted the Intent's self-reported facts), `principal_id` (on whose behalf), `key_id` (which signing key — the mechanical signer, not a governance role), and `approver`/`approval_outcome` are already present. The last pair is genuinely mis-named relative to what it does: it is populated exclusively by `resolution_service.py` when a pending `HUMAN_REVIEW` is resolved — it implements Decision Evidence's **"who reviewed"** role, not **"who approved."** A real, distinct "who approved" concept exists elsewhere in the codebase (`runtime_policy_service.py`'s `approver`/`approver_user_id`), but it belongs to Policy Intelligence's Authority Basis (approving a *policy* into force, governance-time) — it has never applied to an individual decision, and Phase 1 does not force it to.

**Change, additive only, no renaming of existing fields** (consistent with this codebase's own established pattern — `evaluated_mandates` kept alongside `evaluated_mandate_ids`, `matched_mandate_ids` kept alongside `mandate_ids`/`authority_ids`):

| Canon role | Existing field (kept, unchanged) | New field added |
|---|---|---|
| Who asserted | `agent_id` | — (already correctly named and scoped) |
| Who resolved | *(none distinct)* | `resolved_by`: `"agent"` for self-asserted Intent fields, `"runtime_authority_context"` for context-service-computed fields — honest about the fact that Resolver Intelligence doesn't exist yet (§23.4, Baseline), so this field names *which internal source* stood in for a resolver, not a fabricated external one |
| Who is responsible | *(none distinct)* | `responsible_party`: today, identical to `resolved_by`'s value — this collapse is an honest reflection of the current architecture's simplicity (no Resolver Intelligence exists to separate the two roles yet), not a defect papered over |
| Who evaluated | *(implicit — the whole record)* | `authority_version` (§24.2.1) — makes the evaluator's own version explicit rather than only implied by the record existing at all |
| Who approved | *(none at decision level — exists only at Policy level, correctly, in `runtime_policy_service.py`)* | Not added. Forcing a per-decision "approver" field where none of this architecture's real decisions require one as an input would be inventing a role the system doesn't have, which the founder's own rules forbid |
| Who reviewed | `approver`/`approval_outcome` (mis-named, correctly scoped) | `reviewer`/`review_outcome`: exact aliases of the existing values, added at the same call site in `resolution_service.py`, so a reader using canon vocabulary finds the right field without the existing `approver`/`approval_outcome` readers (if any exist in the frontend) ever needing to change |

### 24.2.3 Documentation drift correction

Per baseline §23.5, most drift is already corrected by this specification's existence. What remains, specifically in scope for Phase 1: `ARCHITECTURE.md` at the repository root still describes the legacy Authority/Mandate pipeline as the live decision path (per §16.2 of this specification, already flagged as stale but not yet corrected in the document itself — this specification supersedes it in *effect*, not in *text*). Phase 1 adds a short, prominent notice at the top of `ARCHITECTURE.md` pointing to `SPECIFICATION/00_INDEX.md` as current, rather than rewriting the document's body — consistent with the specification's own "kept in place as a design-time record, superseded where it conflicts" convention (§00_INDEX.md), not a rewrite.

## 24.3 Risk assessment

| Change | Risk | Mitigation |
|---|---|---|
| `DECISION_ENGINE_VERSION` constant | None — a new, unused-elsewhere string constant | N/A |
| `policy_version`/`policy_bundle_hash` on `Decision` dataclass | Low — adds fields to a `@dataclass(frozen=True)`; any code constructing `Decision(...)` positionally rather than by keyword would break | Verified: every construction site in `engine.py` uses keyword arguments already. New fields get defaults (`None`) so no call site requires updating |
| `authority_version`/`policy_version`/`policy_bundle_hash` on Evidence payload | Very low — additive dict keys, `payload_version` unchanged | Matches an already-proven pattern in this exact function three times over |
| `resolved_by`/`responsible_party` on Evidence payload | Low — new, currently-unused-by-any-reader keys | No frontend page currently renders arbitrary Evidence payload keys beyond a fixed set (verified against `LiveEvidence.tsx` in the earlier frontend reconnaissance) — nothing to break |
| `reviewer`/`review_outcome` aliases | Very low — pure duplication of already-set values at the point they're already being set | Zero behavior change; only an additional dict write |
| `ARCHITECTURE.md` notice | None — documentation only | N/A |

**No migration required.** Every change is either a new Python-level constant/dataclass field with a default, or a new JSONB dict key. No Alembic migration, no schema change, no existing column touched.

## 24.4 Architecture conformance checklist (pre-implementation)

- [ ] Every new field is additive; no existing field renamed or removed
- [ ] No existing caller of `Decision(...)`, `Evidence(...)`, `_build_evidence_payload(...)`, or `append_evidence(...)` requires modification to keep working
- [ ] `payload_version` remains `2` — no verifier needs to branch on a new shape
- [ ] `DECISION_ENGINE_VERSION` follows the exact naming/placement convention of `COMPILER_VERSION`
- [ ] No new database migration
- [ ] No frontend change required for this phase (verification-only change: does any page break, not does any page gain a feature)
- [ ] Full backend test suite passes unmodified plus new unit tests for the added fields
- [ ] `ARCHITECTURE.md` change is a pointer, not a rewrite

## 24.5 Implementation roadmap (this phase, in order)

1. `domain/decision/engine.py`: add `DECISION_ENGINE_VERSION`, extend `Decision` dataclass with `policy_version`/`policy_bundle_hash`, extend `ActivePolicy` with `bundle_hash`, thread through `evaluate()`.
2. `services/intent_service.py`: thread the new `Decision` fields into the `Decision` row construction and into `_build_evidence_payload`/`append_evidence`'s new keys (`authority_version`, `policy_version`, `policy_bundle_hash`, `resolved_by`, `responsible_party`).
3. `services/resolution_service.py`: add `reviewer`/`review_outcome` alongside the existing `approver`/`approval_outcome` write.
4. `server/app/db/models.py`: confirm `Policy.bundle_hash` is already selectable via the existing `_DbPolicyStore` — extend `ActivePolicy`'s construction in `intent_service.py`'s `_DbPolicyStore.get_active()` to pass it through.
5. Unit tests: extend existing `tests/unit/test_intent_service.py`-equivalent coverage (or add if none exists at this granularity) to assert the new fields are present and correctly valued for at least one ALLOW, one DENY, and one HUMAN_REVIEW case.
6. Run the full test suite.
7. `ARCHITECTURE.md`: add the superseded-by notice.
8. Architecture Conformance Report (§24.6, produced after implementation, not before).
9. Commit.

## 24.6 Architecture Conformance Report — completed after implementation, see commit accompanying this document's follow-up
