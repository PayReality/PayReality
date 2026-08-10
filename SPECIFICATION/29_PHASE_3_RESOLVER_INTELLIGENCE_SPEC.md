# Part 29 — Phase 3: Resolver Intelligence Specification

**Status:** Phase 3 implementation complete, tested, uncommitted pending this specification. **Baseline:** [23](23_RUNTIME_GOVERNANCE_MIGRATION_BASELINE.md). **Fact catalog:** [28_PHASE_3_CANONICAL_FACT_INTELLIGENCE_SPEC.md](28_PHASE_3_CANONICAL_FACT_INTELLIGENCE_SPEC.md).

## Purpose

Canonical Fact Intelligence names *what a fact means*. Resolver Intelligence names *where its current value comes from, by what method, on whose authority, how fresh it is, and how confident the platform is in it*. Today this platform has exactly two resolution sources, both already implemented, both already correct. This document names them; it does not add a third.

## Resolver catalog

For each fact from the [28](28_PHASE_3_CANONICAL_FACT_INTELLIGENCE_SPEC.md) catalog that is *resolved* (looked up from stored state) rather than supplied directly on the Intent:

| Fact | Resolution Source | Resolution Method | Resolution Authority | Freshness | Confidence | Version |
|---|---|---|---|---|---|---|
| **principal** (identity) | Principal Directory (`principals` table) | `db.get(Principal, agent.acting_for_principal_id)` — single-row primary-key lookup | The Agent's own `acting_for_principal_id` foreign key, set at Agent registration ([11_AGENT_ARCHITECTURE.md](11_AGENT_ARCHITECTURE.md)) | Read fresh on every Intent — no caching layer exists | Certain if the row exists; if it does not, resolution degrades to the raw UUID string rather than failing the Intent (`runtime_truth_service.resolve`'s fallback) | 1 |
| **organization / business_unit / department / team** | The four respective directory tables | `authority_context_service._name_or_none` — primary-key lookup per non-null FK on the resolved Principal | The Principal row's own FK columns | Read fresh on every Intent | Certain if the FK is set and the row exists; `None` if the FK itself is unset (most Principal rows today, since these columns are Phase 1 additive and not yet backfilled) | 1 |
| **role** | Principal row itself | Direct column read, no join | The Principal row | Read fresh on every Intent | Certain if set; `None` if not populated | 1 |
| **risk_level** | Not resolved from storage — computed | `authority_context_service.classify_risk(amount)`, pure function of the Intent's own `amount` | The threshold table inside `classify_risk` itself | Always current — computed at evaluation time, never stored or cached | Certain — deterministic given `amount` | 1 |
| **delegation** | `authority_relationships` table | `authority_context_service._active_inbound_delegations` — indexed query filtered to `kind="delegation"`, `status="active"`, then narrowed in Python by `valid_from`/`valid_to` against the current time | The `AuthorityRelationship` row's own `status`/`valid_from`/`valid_to` columns, set when the relationship was granted | Read fresh on every Intent | Certain for one-hop grants; the resolver explicitly does not walk multi-hop delegation chains, so a Principal's *transitive* authority (a delegates to b delegates to c) is not resolved here at all — see Gap Analysis [32](32_PHASE_3_GAP_ANALYSIS.md) | 1 |
| **action** | Not resolved — supplied directly on the Intent, then validated | `is_recognized_scope(action)` membership check against `KNOWN_SCOPES` | `scope_vocabulary.py`'s own enumeration | N/A — validated, not resolved | Certain: either a member of the enumeration or not; no partial-confidence case exists | 1 |

`amount` and `currency` have no entry above: they are supplied directly by the caller on the Intent and never resolved from any other source. That is a fact about them worth stating plainly, not a gap — nothing today claims otherwise, and this phase does not invent a resolution path for values that are, correctly, caller-supplied.

## The two resolution sources, formally

Runtime Truth ([30](30_PHASE_3_RUNTIME_TRUTH_SPEC.md)) composes exactly these two sources, in this exact order, for every Intent:

1. **Principal Directory** — one primary-key lookup.
2. **Runtime Context Service** (`authority_context_service.resolve_runtime_authority_context`) — up to five further lookups (four directory tables plus the delegation query), all keyed off the Principal resolved in step 1.

No third source exists. No fact in the [28](28_PHASE_3_CANONICAL_FACT_INTELLIGENCE_SPEC.md) catalog is resolved from an external system, a cache, or a second internal table that could disagree with the first.

## What this specification deliberately does not do

- It does not introduce a `Resolver` abstraction, interface, or registry. Every resolution path above is a plain function already in the codebase before this phase began; naming them in a table does not require wrapping them in new infrastructure with nothing yet to plug into it.
- It does not add a confidence *score*. Every resolution above is binary — a row exists or it does not — so a numeric confidence field would represent precision this platform does not actually have.
- It does not resolve the multi-hop delegation gap. That gap is real, already documented in the code's own comments (`authority_context_service.py`'s docstring on `_active_inbound_delegations`) as deliberately deferred to a future phase, and is carried forward unchanged into the Gap Analysis rather than solved here without being asked for.
