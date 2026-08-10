# Part 35 — Phase 4: Intent Intelligence Specification

**Status:** final. **Baseline:** [23](23_RUNTIME_GOVERNANCE_MIGRATION_BASELINE.md), frozen at tag `runtime-governance-phase-3`. **Grounded in:** `schemas/intent.py::SubmitIntentRequest`, `services/intent_service.py::submit_intent`, `domain/decision/engine.py::evaluate`/`build_opa_input`, `domain/runtime_policy/runtime_policy.py::Scope`.

## Purpose

Intent Intelligence answers: **what does an Agent actually have to tell the runtime for a decision to be reachable, and which of the fields on today's request schema exist for that reason versus some other one?** This platform already has one Intent transport object, `SubmitIntentRequest`. This document does not redesign it. It names, for the first time, which of its fields are load-bearing on runtime behavior and which are not — a distinction the code has always drawn implicitly (by which fields it reads versus merely stores) but never stated.

## The transport object, field by field

| Field | Reaches `decision_engine.evaluate()`? | Runtime-required, or implementation-only? |
|---|---|---|
| `agent_id` | Indirectly — resolves the Agent row, whose `acting_for_principal_id` Runtime Truth resolves into `acting_for_principal_id` (a Principal *name*) | **Runtime-required.** Every Decision needs an actor whose scope can be matched. |
| `action` | Directly — the `intent.action` OPA compares against every `RuntimePolicy.scope.action` | **Runtime-required.** Also gates evaluation before OPA is queried at all (`is_recognized_scope`, [28](28_PHASE_3_CANONICAL_FACT_INTELLIGENCE_SPEC.md)). |
| `amount` | Directly — `intent.amount`, plus derives `risk_level` via `classify_risk` | **Runtime-required.** No policy's numeric Condition (`<=`, `>=`, etc.) is reachable without it. |
| `currency` | Directly — `intent.currency`, available to any Condition that references it | **Runtime-required in principle, unused in practice today** — confirmed by search, no shipped `RuntimePolicy` currently conditions on `currency` ([32](32_PHASE_3_GAP_ANALYSIS.md) already noted no currency *vocabulary* exists; this phase adds: no currency *condition* exists either, today). |
| `counterparty` | **No** — never appears in `intent`, `context`, or the OPA input in any form | **Implementation-only today.** Persisted on `Intent.counterparty` for audit/display; `runtime_policy.py::Scope`'s own docstring names `resource` as counterparty's "generic successor," but nothing currently maps a submitted `counterparty` value into a `Scope.resource` match. See Gap Analysis [40](40_PHASE_4_GAP_ANALYSIS.md). |
| `context` (caller-supplied, arbitrary `dict`) | Directly — merged as the base of the `context` dict `decision_engine.evaluate()` receives, so **any** key a caller includes is a legal Condition field path | **Runtime-required as a mechanism, not as any specific field.** No field inside it is mandatory; the mechanism (an open dict a Condition can address by dot-path) is what policies actually depend on. |
| `requested_at` | Directly — becomes `context.timestamp` (via `to_utc_iso`); also the replay-window check at the router layer, before `submit_intent` is even called | **Runtime-required**, in two distinct roles: authentication freshness (router) and an evaluable fact (Condition-addressable). |
| `nonce` | **No** — never reaches `context` or `intent` | **Runtime-required for a different reason**: not a fact Runtime Authority evaluates, but the mechanism `UniqueConstraint(agent_id, nonce)` uses to make replay structurally impossible. Required by the *pipeline*, not by any policy's Condition. |
| `correlation_id` | **No** | **Implementation-only.** Pure caller-side tracking metadata, stored and echoed back nowhere in the Decision/Evidence path. |

## Blueprint, named

**Blueprint** is the architectural name for the subset of an Intent's fields a given `action` actually needs resolved before Runtime Authority can reach a determinate outcome for it. Today this platform has exactly **one** Blueprint, implicit and universal — every recognized `action` (`vendor_payment`, `purchase_order_create`, `wire_transfer`) is evaluated against the identical field set: `action`, `amount`, `currency`, `acting_for_principal_id` (derived), plus whatever the caller chooses to put in `context`. Nothing in the schema, the compiler, or the Decision Engine varies field requirements by `action` — `SubmitIntentRequest` is one flat shape for every action this platform recognizes.

This is a fact about today's implementation, not a limitation this document proposes fixing. `Scope.action` being a member of a compiler-validated enumeration ([28](28_PHASE_3_CANONICAL_FACT_INTELLIGENCE_SPEC.md)) is the only place "which actions exist" is even declared — and it says nothing about per-action field requirements, because none exist yet. A future action type genuinely requiring a field none of today's three actions need (say, a `wire_transfer`-only routing number) would, today, have to travel inside the open `context` dict — the one part of the Blueprint that is already extensible without a schema change, because `decision_engine.evaluate()` and OPA's Condition matching already treat `context` as an open document.

## What this specification deliberately does not do

- It does not introduce a `Blueprint` class, table, or per-action schema. Per this phase's explicit governing instruction, Blueprint is named here as an *architectural concept describing observed behavior* — one universal, implicit Blueprint — not built as new infrastructure with zero current consumers.
- It does not change `SubmitIntentRequest`'s shape. `counterparty` and `correlation_id` remain exactly as implementation-only fields; nothing here proposes removing or repurposing them, since both have real, current uses (display/audit and caller-side tracing respectively) that just happen not to be *runtime-decision* uses.
- It does not wire `counterparty` into `Scope.resource` matching. That wiring, if ever built, is Compiler V2 / Runtime Policy Language scope (already flagged as unaddressed in the Phase 2 conformance report's outstanding issues), not an Intent Intelligence concern — Intent Intelligence's job ends at naming that the gap exists (Gap Analysis [40](40_PHASE_4_GAP_ANALYSIS.md)), not closing it.
