# Runtime Authority Transformation: Architectural Review & Roadmap

Planning only. Nothing in this document has been implemented. Per the directive this document responds to: "do not begin implementation until the architectural review is complete and every recommendation is justified against the existing codebase." Every recommendation below cites the specific existing file/table/function it builds on or replaces.

This document builds directly on two things already in this repository, not from scratch:
1. A full-codebase audit performed earlier in this engagement (Intent model, Decision flow, Evidence, Policy compilation/matching, Authority Graph tables, AI Authority Builder capability, frontend wiring — all independently verified against the code, not assumed).
2. Three existing, unexecuted design docs that overlap substantially with this transformation's goals: `MIGRATION_PLAN_V4.md` (Universal Runtime Authority — vocabulary generalization, legacy retirement), `DOMAIN_REFACTOR_PLAN.md` (the itemized sequencing for domain-adapter extraction), and `DOMAIN_ABSTRACTION.md` (the architecture those items execute against). **Where this transformation's goals overlap with those plans, this document reuses their sequencing and risk analysis rather than re-deriving it.** Where this transformation's goals go further (Authority Graph as real edges, Runtime Authority Context, a Runtime Authority DSL), new analysis follows the same discipline those docs already established: additive, behavior-preserving, verified before any legacy path is retired.

---

## 1. Architectural Review (condensed)

### Strengths — genuinely solid, keep as-is
- Signed, immutable Intent submission with real replay protection (Ed25519 over the raw body, nonce uniqueness, timestamp window).
- A working, fail-closed Decision Engine with a defined, tested effect precedence (`requires_review` > `allow`-not-`deny` > `deny` > fallback deny).
- A real Runtime Policy authoring lifecycle (draft → review → approve → compile → deploy), append-only versioning, and — as of this session — compile-time conflict detection that's exact for numeric/equality/set conditions (`scope_overlap.py`).
- Cryptographically signed, immutable, independently verifiable Evidence, with key-rotation-safe verification (historical records verify against the key that actually signed them, not whatever key is active now).
- `domain/decision/engine.py` is already, today, domain-agnostic — it operates on opaque `dict[str, Any]` and has never referenced a financial field by name. This matters directly for this transformation: the layer this proposal touches least is the layer that's already closest to correct.

### Weaknesses — real, verified problems
- **Two independent, uncoordinated writers to one shared enforcement target.** The legacy Authority/Mandate compiler (`domain/compiler/compiler.py`, `services/policy_service.py`) and the current Runtime Policy Studio pipeline (`compiler_v2`, `runtime_policy_service.py`) both write to the exact same OPA package (`"authorization"`) and the exact same single-active-row slot in the `policies` table, with no coordination. Both routers (`routers/policies.py`, `routers/runtime_policies.py`) are mounted live today. This is the most urgent item in this entire review — see Phase 0.
- **`Constraints.risk_level`/`expires` are stored but never enforced.** Nothing in `rego_generator.py` reads them. A policy author can set a risk level or expiry that silently does nothing.
- **No time-validity window in Compiler V2**, despite the legacy `Mandate` model having one (`valid_from`/`valid_to`, enforced in `compiler.py`'s Rego template). This was dropped, not deliberately omitted.
- **`Organization` never touches policy matching.** It exists purely for RBAC/login; there's no organisational boundary anywhere in `Scope` or the Rego generator.
- **Frontend/backend vocabulary drift**, already named in `DOMAIN_REFACTOR_PLAN.md` item 5, still unresolved: `LiveTestIntent.tsx` hardcodes its own copy of the action vocabulary rather than fetching it.

### Duplicate concepts
- **Two separate "extract authority from a document" pipelines** (`domain/ai_policy_builder/` and `domain/ai_authority_builder/`) with two separate Claude providers, two separate candidate tables' worth of near-identical logic (`PolicyExtractionCandidate` vs. the Authority Builder's reuse of the same table keyed by `corpus_id` instead of `upload_id`). The Authority Builder is a superset; the Policy Builder predates it and is kept mounted "for backward compatibility" per its own router comment.
- **Two "authority" data models that don't reference each other**: the legacy `Principal`/`Authority`/`Mandate`/`Constraint` chain (real FKs, real review workflow) and the newer `AuthorityPrincipal`/`AuthorityResource`/`AuthorityRelationship`/etc. (extraction-only, no FKs, no promotion path except the embedded "policies" category). Both represent "who can do what," built independently, addressing overlapping ground.
  - **Update (Authority-as-a-continuous-object, Stages E-G):** this is no longer true. `AuthorityPrincipal.resolved_principal_id` and `AuthorityRelationship.from_principal_id`/`to_principal_id` now link the discovery model to real `Principal` rows (Stage E/F), and a resolved discovery now promotes into a real `Authority` row at Rule promotion and a real `Mandate` row at Policy deploy (Stage G). The two models reference each other; see `SPECIFICATION/09_AI_AUTHORITY_BUILDER.md` §9 for the corrected promotion path.

### Legacy / dead code
- `Intent.requested_scope` and `Intent.metadata` — declared columns, never written by any code path.
- The legacy Authority/Mandate authoring surface (`routers/policies.py`'s document-upload flow) — still live, still reachable, explicitly named for eventual retirement in `MIGRATION_PLAN_V4.md` Phase D, not yet executed.
- `PLATFORM_POSITIONING.md`'s planned rename of "Authority Modelling Studio" is explicitly gated on the legacy pipeline actually retiring first — another confirmation this retirement is overdue infrastructure debt, not a nice-to-have.

### Architectural inconsistencies
- `AuthorityRelationship` models relationships as free-text `from_principal`/`to_principal` strings, not foreign keys — the one table in the codebase whose name promises graph structure and doesn't deliver it.
- `RUNTIME_POLICY_LANGUAGE.md` (an existing doc) describes `RuntimePolicy` as "inert... not wired into the compiler, Decision Engine, or any router" — this is now **stale**; `RuntimePolicy`/Compiler V2 is the live, primary enforcement path today. Worth a documentation fix independent of this transformation, since a stale doc claiming a core model is unused is actively misleading to the next person who reads it.

### Missing abstractions / runtime concepts
- No real graph edges between authority entities (covered above).
- No context-enrichment step between "Intent submitted" and "OPA queried" — today, exactly two fields get resolved (agent → principal name) and everything else is either a raw Intent field or absent.
- No authoring surface other than the UI form and JSON API — no DSL.
- The domain-adapter generalization (multi-industry vocabulary/Rego-template abstraction) is **already fully designed** in `DOMAIN_ABSTRACTION.md`/`DOMAIN_REFACTOR_PLAN.md`, just not executed. This transformation should not re-design that; it should reference it (see §6, Phase 7).

---

## 2. The Authority Model

The core principle requested — "every component becomes a different representation of the same Authority Model" — is achievable **without a rewrite**, because most of the needed entities already exist in some form. The proposal below is deliberately additive: every change is a new nullable column, a new table, or a new FK, never a removal or rename of anything the current enforcement path depends on.

| Concept | Status today | Proposed change |
|---|---|---|
| **Organisation** | Exists (`Organization`, RBAC-only today) | No schema change. Add an optional `organization_id` FK to `Principal` so it can finally participate in matching/context. |
| **Business Unit / Department** | Does not exist | New, minimal: one small table (`id`, `name`, `organization_id`, optional `parent_id` for department-under-business-unit nesting). Not a deep hierarchy engine — a plain adjacency table is sufficient for the stated use cases (§3). |
| **Principal** | Exists (`Principal`: `id`, `name` only) | Additive columns: `role` (string — matches the precedent already set by `AuthorityPrincipal.role`), `department_id`, `business_unit_id`, `organization_id` (all nullable — zero impact on existing rows or the matching path, which only ever read `.name`). |
| **Agent** | Exists, complete (`Agent`, `acting_for_principal_id`) | No change. |
| **Role** | Not first-class; `AuthorityPrincipal.role` is a free-text extraction field | Start as the new `Principal.role` string column above. Do **not** build a separate Role table/RBAC-style role hierarchy yet — no current use case demonstrates a need for it beyond a label, and speculative normalization is exactly the kind of premature complexity `DOMAIN_REFACTOR_PLAN.md` warns against elsewhere. |
| **Delegation** | Weak: `AuthorityRelationship` with `kind='delegation'`, but `from_principal`/`to_principal` are plain text, not FKs | Rebuild as a real edge table (or extend `AuthorityRelationship` in place): `from_principal_id`/`to_principal_id` as FKs into `principals.id`, `kind` unchanged, `scope` (optional: which action/resource the delegation covers). This is the single highest-leverage schema change in this whole proposal — see §3. |
| **Resource** | Weak: `Scope.resource` is a free string on `RuntimePolicy`; `AuthorityResource` is informational-only, unlinked | Promote to a first-class table: `id`, `name`, `type`, `owner_principal_id` (FK), `organization_id` (FK). `Scope.resource` stays a string for backward compatibility (existing policies are unaffected) but can *optionally* resolve against this table when one exists — additive, never required. |
| **Action / Operation** | Exists as a fixed enum-like vocabulary (`FinancialVocabulary.known_actions`) | Already fully designed: `MIGRATION_PLAN_V4.md` Phase A (organisation-scoped `Vocabulary` table) and `DOMAIN_REFACTOR_PLAN.md` items 2/10 (adapter-owned vocabulary, minimal adapter registry). Reuse that plan directly — do not re-design vocabulary generalization here. |
| **Constraint** | Exists, already generic (`ConditionSet`/`Condition`) | This *already is* a working, generic Constraint model — flat AND, field/operator/value, proven exact for conflict detection (`scope_overlap.py`). No new concept needed. |
| **Risk** | Exists as unused metadata (`Constraints.risk_level`) | Make it real: add an optional `risk_level` comparison as a recognized `Condition` field (e.g. a policy can condition on `context.risk_level`), fed by whatever computes risk upstream (today's `_classify_risk` amount-banding, or something richer later). This makes an existing field do something instead of adding a new one. |
| **Time** | Missing in Compiler V2 (existed in legacy `Mandate.valid_from`/`valid_to`) | Reintroduce as an ordinary `Condition` on `context.timestamp` (already present in every OPA input built by `engine.py`'s `build_opa_input`) — no new entity, no compiler change, just a documented authoring convention plus one example in Policy Studio. |
| **Approval Structures** | Not first-class; the closest precedent is the legacy `requires_dual_approval_above_N` string pattern and Policy's own review workflow | Defer. Extend the `Condition`/Effect vocabulary (e.g. a `require_human_review` effect with a threshold, which already exists) rather than inventing a new entity with no demonstrated real requirement yet. |
| **Authority Relationships (graph edges generally)** | Covered by Delegation + Resource ownership above — a Principal→Resource "owns"/"can_execute" edge falls naturally out of the `owner_principal_id` FK and a Delegation-shaped relationship type, without inventing a generic edge-typing system nobody has asked for yet. |

---

## 3. Proposed Runtime Authority Architecture

Every layer below is marked with its actual status. Nothing marked `[EXISTS]` changes in this proposal.

```
Enterprise Governance Documents                      [EXISTS] — AI Authority Builder upload
        ↓
Authority Extraction (Claude / fake provider)         [EXISTS] — unchanged
        ↓
Authority Model                                       [EXTEND] — §2's additive schema
   (Organisation, Business Unit, Department,
    Principal + role/org/dept, Resource,
    Delegation as real edges, Constraint = Condition)
        ↓
Authority Graph                                       [EXTEND] — real FK edges replace
                                                        AuthorityRelationship's text fields
        ↓
Runtime Authority Context                              [NEW] — see below
        ↓
Authority Resolution (context enrichment only)         [NEW, narrow] — see below
        ↓
Runtime Policies                                       [EXISTS] — Compiler V2, unchanged
        ↓
Decision Engine                                        [EXISTS] — unchanged
        ↓
Evidence (+ chaining)                                  [EXTEND] — additive, see §6 Phase 5
```

**Runtime Authority Context** is the one genuinely new runtime object this proposal introduces. It is *not* a replacement for `Intent` — `Intent` stays exactly as it is today (signed, immutable, minimal). The Context is an ephemeral, request-scoped enrichment built *from* the Intent plus the Authority Model, immediately before the OPA query: it resolves the submitting Agent's Principal, that Principal's department/business unit/organisation (via §2's new FKs), and its delegation chain (by walking the new Delegation edges — a handful of ordinary SQL joins, not a graph engine). The enriched result is added to the existing `context` dict already passed into `build_opa_input()` — meaning **existing policies' conditions can immediately reference `context.department`, `context.organization`, etc., the moment they're authored to, with zero change to the Rego generator, the compiler, or OPA.** This is the cheapest, highest-leverage part of the whole transformation, because it reuses the exact mechanism (`Condition` on an arbitrary `context.*` field) that already exists and is already proven.

**Authority Resolution**, scoped narrowly to this context-enrichment role, is real, valuable, and low-risk. **It is deliberately not scoped to policy pre-filtering/indexing** — see §8 for why that's a different proposal with a different risk profile that isn't justified yet.

**Answering the four example graph queries from the original request**, concretely, with this design:
- *"Who can approve this payment?"* — `SELECT` principals whose Delegation edges or direct grants cover the resource/action, joined through the enriched Context.
- *"Which authority reaches this agent?"* — walk the Agent → Principal → Delegation-edge chain (a recursive CTE or a handful of app-level joins over the new FK table; no graph database required at this scale).
- *"Which policies depend on this principal?"* — already answerable today: `RuntimePolicyRecord.scope.principal` is a string match against `Principal.name`; trivial to index.
- *"What breaks if this authority changes?"* — the delegation-chain walk above, run in reverse, surfaced as a warning before a Principal/Delegation edit is saved. New, but small — an application-level function over the same FK table, not new infrastructure.

None of these require a graph database, a graph query language, or a traversal engine — see §8.

---

## 4. Component Dependency Graph

```
                                ┌────────────────────┐
                                │  Governance Docs     │
                                └──────────┬───────────┘
                                           │
                                ┌──────────▼───────────┐
                                │ AI Authority Builder  │  [unchanged]
                                └──────────┬───────────┘
                                           │ writes
                                ┌──────────▼───────────┐
                     ┌──────────┤   Authority Model      │◄─────────────┐
                     │          │ (Principal+, Resource, │              │
                     │          │  Delegation edges,      │              │ authored via
                     │          │  Vocabulary [Migration  │              │ Runtime Authority DSL
                     │          │  Plan V4 Phase A])      │              │  [new authoring surface]
                     │          └──────────┬───────────┘              │
       read by       │                     │ generates drafts          │
   Authority          │                     ▼ (reuses existing          │
   Resolution         │          ┌──────────────────────┐              │
   (context           │          │  RuntimePolicy         │◄─────────────┘
   enrichment)         │          │  (Compiler V2)          │  [unchanged compiler/Rego/OPA]
                     │          └──────────┬───────────┘
                     │                     │ compiles/deploys (unchanged)
                     │          ┌──────────▼───────────┐
                     └─────────►│   Decision Engine       │  [unchanged]
                                └──────────┬───────────┘
                                           │
                                ┌──────────▼───────────┐
                                │  Evidence (+chaining)  │  [additive]
                                └────────────────────────┘
```

The load-bearing insight: **Runtime Authority Context / Authority Resolution sits beside the existing pipeline, feeding it richer `context` data — it does not sit between Intent and the Decision Engine as a gate that could reject or filter policies.** That distinction is what keeps this entire proposal additive rather than a rewrite of the one component (`decision/engine.py`) that's already correct.

---

## 5. Migration Strategy

Follows the exact discipline `MIGRATION_PLAN_V4.md` and `DOMAIN_REFACTOR_PLAN.md` already established for this codebase, because it's the right discipline, not because of precedent alone:

1. **Additive schema only.** Every new column is nullable; every new table is new, referenced optionally. Zero existing `RuntimePolicyRecord`, `Intent`, `Decision`, or `Evidence` row changes shape or meaning.
2. **The compiler is the load-bearing wall — touch it last, and only for genuinely new capability (time/risk conditions), never for restructuring.** Any change near `compiler_v2.py`/`rego_generator.py`/`bundle_builder.py` needs the same byte-identical-output verification discipline `DOMAIN_REFACTOR_PLAN.md` item 3 already prescribes for its own, unrelated compiler change.
3. **Legacy retirement is a separate, explicit, later decision** — resolving the two-OPA-writer risk (Phase 0 below) means *coordinating* the two paths or disabling the legacy path's *authoring* surface, not deleting `compiler.py`/`policy_service.py`/`Authority`/`Mandate` outright. `MIGRATION_PLAN_V4.md` Phase D already designed the backfill-and-disable approach for exactly this; reuse it rather than re-deriving a new one.
4. **New capability ships as a new, optional authoring surface (the DSL) targeting the existing internal representation (`RuntimePolicy`), never a new compilation backend.** This is the same pattern `MIGRATION_PLAN_V4.md` Phase C already uses for Policy Studio and the AI Policy Builder — multiple authoring surfaces, one compiler.

---

## 6. Phased Implementation Plan

Re-sequenced from the original 13-phase request by actual dependency and risk, not by the order originally listed. Phases explicitly deferred are named in §8, not silently dropped.

| Phase | What | Depends on | Risk |
|---|---|---|---|
| **0** | Resolve the two-OPA-writer conflict: either disable the legacy authoring surface (`MIGRATION_PLAN_V4.md` Phase D's backfill-and-disable) or add explicit coordination between both deploy paths | Nothing — this is a live risk today | Low effort, but urgent; skipping this is the one thing in this whole plan that could cause a real incident |
| **1** | Authority Model schema: `Principal` gets `role`/`department_id`/`business_unit_id`/`organization_id`; new `Department`/`BusinessUnit`/`Resource` tables; `AuthorityRelationship` gets real FK columns alongside (not replacing) its text columns | Phase 0 (don't build on top of an uncoordinated write path) | Low — additive only |
| **2** | Runtime Authority Context: the enrichment step, populating `context` before `build_opa_input()` with resolved department/org/delegation-chain data | Phase 1 | Low — reuses the existing `context`/`Condition` mechanism verbatim |
| **3** | Time and Risk as real, enforced `Condition` fields (`context.timestamp`, `context.risk_level`) | Phase 2 (risk/time need to actually be *in* context to be conditioned on) | Low |
| **4** | Runtime Authority DSL: a parser producing `RuntimePolicy` objects, feeding the unchanged `compile_bundle()` | Nothing structural — can start anytime, but land after Phase 1 so the DSL can express department/org/resource from day one instead of needing a follow-up revision | Medium — the DSL's own grammar/parser is real, net-new work; its blast radius on the rest of the system is low, since it only ever produces the same `RuntimePolicy` object every other authoring surface already produces |
| **5** | Evidence chaining (each Evidence record references the hash of the prior one for its Principal/Agent, or globally) | Nothing new — additive to the existing signing path | Medium — must not invalidate any existing signed record; add a `payload_version` field the same way `DOMAIN_REFACTOR_PLAN.md` item 8 already recommends for its own, differently-motivated Evidence change |
| **6** | Generalize the existing candidate-promotion mechanism (`ai_policy_builder_service.promote_candidate`) so any Authority Model entity (not just an extracted policy candidate) can generate a `RuntimePolicy` draft | Phases 1-2 | Low-medium — this is extending a proven mechanism, not building a new one |
| **7** | Domain adapters (Payments/Procurement/Banking/etc.) | A real second industry customer — see `DOMAIN_REFACTOR_PLAN.md`, unchanged | Not started until that precondition is real; reuse that plan exactly, don't re-plan it here |

---

## 7. Risks and Trade-offs Per Phase

| Phase | Foundational or optional | Why it matters | What breaks if skipped/rushed |
|---|---|---|---|
| 0 | **Foundational, urgent** | Two writers to one enforcement target is a live correctness risk, not a future one | A deploy through either path can silently undo the other's active policy with no error |
| 1 | Foundational | Every later phase (Context, DSL, Delegation graph) needs somewhere to store the data | Nothing breaks if skipped — but nothing else in this plan can start either |
| 2 | Foundational for the stated vision | This is what makes "hundreds of policies across departments/regions" actually expressible without inventing a new comparison mechanism | Without it, department/region conditions have nowhere to read from at decision time |
| 3 | Optional but cheap | Real product value (time-boxed authority, risk-gated review) at very low cost given Phase 2 already exists | Low cost to defer; low cost to do — do it once Phase 2 lands |
| 4 | Foundational for the "own language" ambition specifically | A DSL is the single most customer-visible piece of this whole transformation | If rushed, a bad grammar decision is expensive to change later (every authored policy would need re-parsing); worth real design time, not a sprint |
| 5 | Foundational for the audit/insurer pitch | Chaining is what turns "this record is authentic" into "this whole history is authentic" | Must version the payload shape or risk silently changing what "verify" means for old records |
| 6 | Optional until Phase 1-2 exist | High-value once the Authority Model has real data worth generating policies from | Low risk either way — it's additive to a mechanism that already works |
| 7 | **Explicitly not now** | Real industries have real, differing requirements no amount of internal design can guess correctly | Building this speculatively is exactly the premature complexity `DOMAIN_REFACTOR_PLAN.md` already warned against for a different but related effort |

---

## 8. What Should NOT Be Built Yet — and why

**Policy pre-filtering / a candidate-selection index (the original request's Phase 5-6 "Authority Resolution Engine" and Phase 6 "Runtime Policy Selection").** This is the one recommendation in this document that pushes back directly on the original request, and it deserves a direct explanation. OPA evaluates an entire compiled Rego bundle in a single, fast, in-memory query — it is specifically designed for exactly this workload, and "hundreds" (or even many thousands) of small rules is not a demonstrated performance problem anywhere in this codebase or in OPA's own published benchmarks. Building a separate pre-filtering layer that decides *which* policies OPA even sees would:
- Solve a performance problem that doesn't exist yet, at real engineering cost.
- Introduce a **new correctness risk that's worse than the problem it solves**: if the pre-filter ever wrongly excludes a policy that should have applied, that's a silent, hard-to-detect authorization gap — precisely the failure mode this platform's whole design philosophy (fail-closed, deterministic, "never a silent guess") exists to prevent. "Evaluate everything, resolve conflicts deterministically" is *safer* than "guess what's relevant first."
- Recommendation: keep evaluating every active policy. Revisit only if real production telemetry ever shows OPA query latency actually degrading at real policy-count scale — and even then, the first fix should be OPA's own partial-evaluation/indexing features, not a hand-rolled pre-filter.

**A full graph database or graph query language.** §3 shows the four example queries the request names are all answerable with ordinary foreign keys and SQL joins (or one recursive CTE for delegation-chain walking) once §2's Delegation edges exist. Standing up a graph database or a bespoke traversal DSL for a handful of shallow queries is infrastructure the actual requirements don't justify yet.

**Domain adapters for Payments/Procurement/Banking/Insurance/Healthcare/Government/Manufacturing.** `DOMAIN_REFACTOR_PLAN.md` already says this precisely and explicitly, for a closely related reason: "Building one before there's a real customer need for it would be exactly the kind of premature complexity this whole engagement has been careful to avoid." That reasoning applies without modification here.

**Replacing or abstracting away OPA (native runtime engine, WASM, edge runtime).** OPA is working, proven in this codebase, and not the bottleneck anywhere in the current architecture. An execution-adapter abstraction is speculative infrastructure for a migration with no current driver. If this ever becomes real, it's a much smaller change than it sounds — `HttpOpaClient` is already the single, narrow seam every OPA interaction goes through — but building the abstraction before there's a second real backend to abstract *to* is guessing at an interface, the same mistake `DOMAIN_REFACTOR_PLAN.md` warns against for its own adapter registry (item 10: "a registry designed against zero real second cases is a guess, not an architecture").

**A first-class Approval Structures entity, or a Role table with a real hierarchy.** No current requirement demonstrates a need for either beyond what an extended `Condition`/`Effect` vocabulary and a plain string field already cover. Add the table only once a real authoring need proves the string/condition isn't enough — not before.

**Redesigning vocabulary/terminology normalization.** `MIGRATION_PLAN_V4.md` Phase A already designed this (an organisation-scoped `Vocabulary` table, seeded from today's `FinancialVocabulary`). Building a second, competing vocabulary-normalization concept as part of this transformation would create exactly the kind of duplicate-concept problem §1 already flags as a weakness. Reuse that plan; don't re-solve it.
