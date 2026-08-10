# Part 32 — Phase 3 Gap Analysis

**Status:** final. **Baseline:** [23](23_RUNTIME_GOVERNANCE_MIGRATION_BASELINE.md). **Scope:** Canonical Fact Intelligence, Resolver Intelligence, Runtime Truth only — Intent Intelligence, Context Intelligence, and Integrity Intelligence gaps belong to Phase 4/5 and are out of scope here.

## What doesn't exist today

- **A currency vocabulary.** `currency` is an unconstrained string end to end (schema, service, Rego). No enumeration, no ISO-4217 validation, nothing. Confirmed absent by direct search across `server/app`.
- **A generalized Fact Registry.** No table or module maps fact name -> owner -> version for facts as a category; the [28](28_PHASE_3_CANONICAL_FACT_INTELLIGENCE_SPEC.md) catalog is a document, not runtime infrastructure.
- **Fact versioning beyond `1`.** No fact this platform resolves has ever had a second, coexisting definition of what it means. Nothing needed to be built to accommodate an event that hasn't happened.
- **A Resolver abstraction with pluggable sources.** Every fact has exactly one resolution source today; an interface for swapping sources would serve a requirement that doesn't exist yet.
- **Multi-hop delegation resolution.** `_active_inbound_delegations` resolves one hop only. A Principal's transitive authority through a chain of delegations is not computed anywhere in the decision path.
- **Resolution confidence scoring.** Every resolution in this platform is binary (row exists / does not); no fact has a source with partial reliability that would justify a numeric confidence field.
- **Field-level vocabulary validation in Compiler V2.** Its `Vocabulary` protocol validates `action` only; `resource` gets a non-blank check, nothing richer. This gap predates Phase 3 (noted in the Phase 2 conformance report's outstanding issues) and remains open.

## What should intentionally remain absent

- **A currency vocabulary**, unless and until a real multi-currency policy requirement appears. Building one now would be exactly the "infrastructure that did not already exist" this phase's directive says to stop and justify before building — and no such requirement exists today.
- **A Fact Registry / versioning table.** The [28](28_PHASE_3_CANONICAL_FACT_INTELLIGENCE_SPEC.md) catalog already answers "what does this platform consider canonical fact intelligence" as a document; promoting it to a database table buys nothing until a fact's meaning actually needs to change while an old meaning is still in flight.
- **A Resolver interface/abstraction.** One source per fact, always has been. An abstraction over a set of one is speculative by definition.
- **Resolution confidence scoring.** Introducing a number where the true state is binary would manufacture false precision, not real information.

## What should become future extension points

- **Multi-hop delegation resolution** is the one gap here with a plausible near-term trigger: an audit or impact-analysis feature (already anticipated in `authority_context_service.py`'s own comments as Phase 4 scope) would need to walk the delegation graph beyond one hop. When that feature is scoped, `_active_inbound_delegations`'s single-hop query is the natural extension point — it already isolates delegation resolution behind one function.
- **A currency vocabulary**, if the platform ever supports policies conditioned on currency (e.g. "USD wire transfers over $X require review, EUR does not"). The extension point is `Vocabulary`'s existing protocol shape in `compiler_v2.py` — a second method (`is_valid_currency`) would follow the same pattern already established for `action`, not a new one.
- **Field-level vocabulary validation** generally, if a second domain adapter is ever built (`DOMAIN_ABSTRACTION.md` already anticipates this). The `Vocabulary` Protocol is already the extension point; it simply has one implemented method today because `action` is the only field with a current validation requirement.

## What this phase did not need to solve

None of the gaps above blocked Phase 3's actual objective (naming facts and resolvers that already exist, and formalizing the resolution boundary). Each is recorded here so it is visible and intentional, not because Phase 3 left work half-done.
