# Domain Refactor Plan

Nothing in this document has been executed. Every item below is a proposal, not a change log. See `DOMAIN_ABSTRACTION.md` for the architecture and reasoning this plan is executing against.

Ordering matters here: items are sequenced so that early items are valuable on their own (architecture hygiene, no behavior change) independent of whether a second adapter is ever built, while later items only pay off once there's an actual second domain to build for. Nothing after item 5 should be started before a real second adapter is being committed to, not a hypothetical one.

---

## 1. Extract a Financial Adapter module boundary

**Current location:** Financial logic is spread across `intent_service.py`, `compiler.py`, `scope_vocabulary.py`, and `domain/extraction/`, with no explicit module boundary separating "engine" from "financial domain."

**Reason:** Every later step needs somewhere to move logic *to*. This step creates that seam without moving any behavior yet, so it's safe to do first and independently of everything else.

**Risk:** Very low. This is a pure code-organization move: create `server/app/domain/adapters/financial/` (or similar), define a `DomainAdapter` Protocol describing the responsibilities named in `DOMAIN_ABSTRACTION.md` (action vocabulary, Intent payload shape, Rego template, conflict rule, risk classification, Evidence domain-fields, extraction mapping), and have the Financial adapter's initial implementation simply call today's existing functions unchanged.

**Breaking change?** No. Internal-only; no API, schema, or behavior change.

**Migration strategy:** Define the Protocol first, write one passing implementation (Financial) that wraps existing code, verify all 36 existing tests still pass unmodified. No callers change yet, this step only creates the destination, later steps redirect callers to it.

**Estimated effort:** Small (a day or so of focused work).

**Priority:** Do first, regardless of anything else. This is the foundation every other item depends on.

---

## 2. Make the action vocabulary adapter-owned

**Current location:** `server/app/domain/decision/scope_vocabulary.py`'s `KNOWN_SCOPES` frozenset, hardcoded to the three financial scopes.

**Reason:** The *mechanism* (fixed enumeration, unrecognized action fails to `HUMAN_REVIEW`) is correct and domain-independent. The *content* is financial. Separating them lets a future adapter supply its own vocabulary without touching the fail-closed mechanism.

**Risk:** Low. `is_recognized_scope()`'s call sites (`intent_service.submit_intent`) need to ask the active adapter for its vocabulary instead of importing the module-level constant directly, but the fail-closed behavior itself doesn't change.

**Breaking change?** No, if the Financial adapter's vocabulary is set to exactly today's three scopes.

**Migration strategy:** Move `KNOWN_SCOPES` into the Financial adapter as a property/method on the Protocol from item 1. Add a unit test asserting the Financial adapter's vocabulary still contains exactly `{vendor_payment, purchase_order_create, wire_transfer}`, so this can never silently drift during the move.

**Estimated effort:** Extra small.

**Priority:** Do alongside item 1, same PR is reasonable.

---

## 3. Make the compiler adapter-aware

**Current location:** `server/app/domain/compiler/compiler.py`'s `REGO_TEMPLATE` constant and `compile_authorities()`, which unconditionally uses it.

**Reason:** This is the deepest coupling in the system (see `DOMAIN_ABSTRACTION.md`). The compiler needs to ask "which adapter is this Authority's domain, and what's its Rego template" instead of assuming one template for everyone, before any second domain's Authority shape could ever be represented.

**Risk:** High. `bundle_hash`'s determinism guarantee ("the same Authority set compiled twice produces identical output," spec 12.4 Stage 6) must hold under the new adapter-dispatch path exactly as it does today for the Financial adapter. Getting this wrong would silently break policy version integrity, which is one of the most audit-sensitive guarantees in the whole system.

**Breaking change?** No, if done correctly, since the goal is byte-identical output for the Financial adapter before and after.

**Migration strategy:** 
1. Move `REGO_TEMPLATE`, `_check_conflicts`, and `_parse_conditions` into the Financial adapter, unchanged.
2. Add a new test that compiles the same fixed Authority set through both the old direct path and the new adapter-dispatched path and asserts identical `rego_source`, `mandates_data`, and `bundle_hash`.
3. Only once that test passes, delete the old direct path and make `compile_authorities` route through the adapter exclusively.
4. Run the full existing compiler test suite (`test_compiler.py`) against the new path unmodified, since those tests are the closest thing to a regression contract for this exact guarantee.

**Estimated effort:** Medium (this is the one item in this plan worth budgeting real review time for, not rushing).

**Priority:** Do before item 6 or 7 (schema changes); this needs to be solid first since those items depend on the compiler already being adapter-aware.

---

## 4. Extract risk classification into the adapter

**Current location:** `intent_service._classify_risk(amount)`, a dollar-amount banding heuristic called unconditionally inside `append_evidence`.

**Reason:** Risk classification is domain-specific by nature (dollar bands for Financial, something else entirely for a domain with no numeric amount concept at all). It shouldn't live inside what's meant to be the generic evidence-building path.

**Risk:** Low. This is a self-contained function with a clear input/output contract; moving it behind an adapter hook is mechanical.

**Breaking change?** No, if the Financial adapter's thresholds stay at today's values ($250k/$100k/$50k bands).

**Migration strategy:** Move the function into the Financial adapter unchanged, have `append_evidence` call `active_adapter.classify_risk(...)` instead of the module-level function directly. Existing tests covering these thresholds should be retargeted at the adapter, not deleted.

**Estimated effort:** Extra small.

**Priority:** Do alongside item 1-2; low-risk, no reason to delay.

---

## 5. Fix the frontend/backend action-vocabulary drift

**Current location:** `src/app/live/pages/LiveTestIntent.tsx` hardcodes its own `KNOWN_SCOPES` array, a second, independently-maintained copy of the backend's vocabulary.

**Reason:** This is a real, pre-existing bug, independent of the whole domain-abstraction question: if the backend's vocabulary ever changes without a matching frontend edit, the two silently diverge and a user could submit an action the frontend thinks is valid but the backend doesn't recognize (or vice versa).

**Risk:** Very low to fix; the current state is the actual risk.

**Breaking change?** No.

**Migration strategy:** Simplest fix: expose the active adapter's vocabulary via an API (e.g., a small addition to an existing endpoint, or a new lightweight one) and have the frontend fetch it instead of hardcoding a copy. This also happens to be a natural, small proof that the adapter boundary from item 1-2 is real: if the frontend can get the vocabulary from an API backed by the adapter, the abstraction is doing real work already.

**Estimated effort:** Small.

**Priority:** Worth doing on its own merits regardless of the rest of this plan; bundle with item 2 since they touch the same concept.

---

## 6. Move `Intent.amount`/`currency`/`counterparty` into `Intent.context`

**Current location:** `server/app/db/models.py`'s `Intent` table (dedicated `Numeric(18,2)`, `String(3)`, `Text` columns) and `SubmitIntentRequest` (`schemas/intent.py`, required top-level API fields).

**Reason:** `Intent.context` already exists as a JSONB column for exactly this kind of variable-shape, domain-specific data. Keeping amount/currency/counterparty as dedicated columns is the single biggest reason a non-financial Intent can't be represented today without a schema change.

**Risk:** High, for two independent reasons: (1) this is a live production schema with the field already in use, requiring a real data migration, not just a fresh-table change; (2) `SubmitIntentRequest` is the public API surface for `POST /v1/intents`, and this directive is explicit that no breaking API changes are acceptable.

**Breaking change?** Must not be. The migration path is additive: add the ability for the request to also carry a generic payload/context object, keep `amount`/`currency` accepted exactly as today (populating `context` under the hood if not separately provided), and only consider deprecating the dedicated top-level fields much later, as a deliberate, separately-decided API version bump, not as part of this work.

**Migration strategy:** 
1. Add the `content`-in-JSONB pattern already proven safe by the recent document-storage migration (see `ARCHITECTURE.md`'s data model notes) as the template: additive column, backfill, then only remove the old column once nothing reads it.
2. Keep `Intent.amount`/`currency` as real columns for now (the Financial adapter still needs fast, indexable access to them for `_classify_risk` and reporting); the actual target state might be "generic `context` JSONB is the source of truth, with the Financial adapter-specific columns becoming a queryable projection of it," not full removal of typed columns. Worth deciding deliberately rather than assuming "remove the columns" is the only valid target.
3. Land this only after item 3 (compiler adapter-awareness) is done and stable, since the compiler's Rego template currently reads `input.intent.amount` directly; that reference needs to move to the Financial adapter's own template before the underlying data's location changes.

**Estimated effort:** Medium to large, depending on how much of "keep typed columns as a projection" versus "fully generic" is decided.

**Priority:** Do only once there's a real second adapter being built that needs this, not preemptively. Item 3 already removes the compiler's *logic* coupling; this item is about the *storage* coupling, which is lower-value to fix speculatively.

---

## 7. Move `Authority`/`Mandate`'s financial fields into their existing JSONB columns

**Current location:** `Authority.limit_amount`/`currency`/`extracted_limit_amount`/`extracted_currency`, `Mandate.max_amount`/`currency`/`review_threshold`.

**Reason:** Same reasoning as item 6, one layer up the pipeline: `Authority.conditions` and a Mandate-side equivalent already exist as the flexible-data escape hatch.

**Risk:** High, same category as item 6, plus this one also touches the document-extraction providers (`CandidateAuthority`'s shape). (Update: `LiveDocuments.tsx`, this item's original other blast-radius concern, was later fully retired -- `SPECIFICATION/17_LEGACY_COMPONENTS.md` -- so it no longer adds to the risk here.)

**Breaking change?** Same constraint as item 6: additive only, no removal of existing behavior without a deliberate, separate decision.

**Migration strategy:** Do not start this until item 3 and item 6 are both done and stable. This is the item most likely to reveal that "fully generic Authority/Mandate" needs a real second adapter's actual requirements to design correctly, rather than guessing at a shape from first principles. Strongly consider deferring the *storage* migration until a second adapter is actually being built, and treating this document's classification as sufficient preparation until then.

**Estimated effort:** Large.

**Priority:** Lowest priority in this plan. Do not do this speculatively.

---

## 8. Extract the Evidence domain-fields shape from the generic envelope

**Current location:** `intent_service._build_evidence_payload()`, which builds both the generic envelope (`decision_id`, `agent_id`, `action`, `matched_mandate_ids`, `authority_outcome`, `approval_outcome`, `recorded_at`) and the financial-specific fields (`amount`, `risk_classification`) in one function.

**Reason:** Splitting these lets the engine own the generic envelope permanently while each adapter contributes its own domain fields, without the engine needing to know what those fields are.

**Risk:** Medium-high. Every Evidence record ever signed has today's exact combined shape. Any change to what gets signed going forward must not retroactively invalidate the signature-verification story for historical records, since a regulator or insurer relying on `SECURITY.md`'s "independently verifiable evidence" claim needs old records to keep verifying exactly as they do today.

**Breaking change?** Not to historical records (their payload and signature don't change, they were signed with a specific shape and stay verifiable against it). Is a change to the shape of *newly created* Evidence going forward, which should be treated as a versioned schema change (e.g., an explicit `payload_version` field) so tooling can tell old-shape and new-shape Evidence apart, rather than silently assuming one shape forever.

**Migration strategy:** Add a `payload_version` (or equivalent) field to the Evidence payload itself as part of this change, even though nothing requires it today, specifically so this kind of evolution has a clean seam next time, and so today's records are unambiguously identifiable as "version 1" going forward.

**Estimated effort:** Medium.

**Priority:** Do after item 3 and 4, before item 6/7. This is lower-risk than the storage migrations and can be validated independently.

---

## 9. Extract the document-extraction mapping into the adapter

**Current location:** `domain/extraction/provider.py`'s `CandidateAuthority` dataclass, `claude_provider.py`, `fake_provider.py`, all shaped around "principal, scope, limit amount, currency, conditions."

**Reason:** A different domain's document intelligence would extract structurally different candidates (see `DOMAIN_ABSTRACTION.md`'s Healthcare/Identity examples, which have no numeric-limit concept at all).

**Risk:** Medium. The Claude-backed extraction prompt itself is tuned for financial delegation-of-authority language; a generic interface here is only as good as whether a second adapter's actual extraction needs resemble this one's shape, which is unknown until there's a real second case.

**Breaking change?** No, if the Financial adapter's extraction behavior is preserved exactly.

**Migration strategy:** Move `CandidateAuthority` and both providers behind the adapter Protocol from item 1, but don't attempt to generalize the Claude prompt itself speculatively. Revisit the prompt only once a second adapter with real extraction needs exists.

**Estimated effort:** Small to medium.

**Priority:** Do alongside item 1, since it's a similarly low-risk pure-extraction move, but genuinely low-value until a second adapter needs a different extraction shape.

---

## 10. Introduce an adapter registry

**Current location:** Doesn't exist yet; today there is implicitly exactly one adapter and nothing selects it.

**Reason:** Every item above assumes something resolves "the active adapter" for a given request/Policy/Principal. That resolution mechanism needs to exist, even trivially (a single hardcoded default), before item 3 can be written in a way that's actually extensible rather than just refactored-in-place.

**Risk:** Low today (one adapter, trivial resolution), but this is the piece most likely to need real redesign once a second adapter exists (e.g., is the adapter chosen per-Policy? Per-Principal? Per-tenant?). Don't over-design this now.

**Breaking change?** No.

**Migration strategy:** Start with the simplest possible thing that could work: a single module-level "the active adapter is Financial" constant, resolved the same way regardless of request. Do not build multi-adapter selection logic until there's a second adapter to select between; a registry designed against zero real second cases is a guess, not an architecture.

**Estimated effort:** Extra small, deliberately.

**Priority:** Do as part of item 1, as the mechanism items 2-4 call into. Keep it intentionally minimal.

---

## What this plan deliberately does not include

- Any actual second adapter (Insurance, Identity, Contracts, Procurement, Infrastructure, Healthcare). Building one before there's a real customer need for it would be exactly the kind of premature complexity this whole engagement has been careful to avoid elsewhere (see `SECURITY.md`, `VERSION_3_ROADMAP.md` for the same discipline applied to other decisions).
- Any change to website messaging, investor messaging, product positioning, demo flow, or customer journey, per this directive's explicit instruction.
- Any change to the current demo's behavior or the existing enterprise conversations' experience. Items 1, 2, 4, 5, 9, and 10 are zero-behavior-change extractions; items 3 and 8 are designed to be behavior-preserving and verified as such before landing; items 6 and 7 are explicitly deferred rather than attempted speculatively.

## Suggested sequencing summary

| Order | Item | Effort | Priority |
|---|---|---|---|
| 1 | Extract Financial Adapter module boundary | S | Do first |
| 1 | Introduce adapter registry (minimal) | XS | Do first, alongside item 1 |
| 2 | Make action vocabulary adapter-owned | XS | Alongside item 1 |
| 2 | Extract risk classification into adapter | XS | Alongside item 1 |
| 2 | Extract document-extraction mapping | S-M | Alongside item 1 |
| 3 | Fix frontend/backend vocabulary drift | S | Independent bug fix, do anytime |
| 4 | Make the compiler adapter-aware | M | After the above, before schema changes |
| 5 | Extract Evidence domain-fields shape (with payload versioning) | M | After compiler item |
| 6 | Move Intent's financial fields into context | M-L | Only once a second adapter is real |
| 7 | Move Authority/Mandate's financial fields into JSONB | L | Only once a second adapter is real, lowest priority |
