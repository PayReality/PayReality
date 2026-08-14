# CTO Handover Guide

**Start here.** This document orients whoever owns this platform's engineering long-term; it points to the deeper documents rather than duplicating them, so nothing here needs updating independently of the sources it references.

## Read these four documents, in this order, before touching anything

1. `ARCHITECTURAL_DECISION_HISTORY.md`: why every major structural decision was made, in the order the decisions actually happened. Read this first; most "why is it built this way" questions are answered here, not in code comments.
2. `ENGINEERING_PRINCIPLES.md`: the standing conventions enforced across every milestone. Read this before making any change that touches multi-tenancy, RBAC, cryptography, or AI-provider code; several of these principles are not obvious from reading a single file in isolation.
3. `TECHNICAL_DEBT_REGISTER.md`: every known, real, currently-open gap, with where it was found and its current status. This is the honest state of things; treat it as a living document, and update it (add, don't silently remove) whenever a new gap is found or an old one is closed.
4. `SPECIFICATION/`: the detailed, part-by-part technical reference for every subsystem (Runtime Authority, Runtime Policies, OPA integration, Evidence, Authority Intelligence, Security Model, Current Limitations, and more), maintained continuously across this platform's entire history. This is the reference to consult for "exactly how does X work today," not this document.

## The one sentence that governs every decision in this codebase

**AI proposes, a human decides, OPA enforces deterministically.** Every architectural choice that seems unusual, extracting candidates instead of activating them directly, keeping Enterprise Knowledge unbuilt rather than bolting live external lookups into policy evaluation, choosing OPA over a custom engine, traces back to protecting this one sentence. If a future change would blur it, that change needs the same level of scrutiny the original boundary got, not a routine code review.

## How this platform actually got built, in one paragraph

Nine milestones, each with a narrow, explicit scope and its own verification standard: build the Runtime Authority mechanism first, single-tenant, prove it worked (pre-Milestone 2); retrofit real multi-tenancy once the mechanism was proven (Milestones 2-3), verified with an independent adversarial audit before and a real second organization after; migrate from a zero-cost pilot host to real Azure production infrastructure (Milestones 4-7), each step gated on live verification of the previous one, never on a calendar date; align the external and internal narrative with what had actually been built (Milestone 8); and begin the transition from platform construction to company execution (this milestone). The throughline across all nine: never claim something works without checking it directly against a live system, and say "NOT VERIFIED" plainly when a check genuinely can't be done, rather than assume.

## What to do in your first week

- Read the four documents above, in order.
- Run the full test suite (`server/tests/unit`, `server/tests/integration`) and the smoke test (`scripts/smoke_test.py`) against a real environment, so you have direct, current proof of what actually passes today, not an assumption carried over from this document.
- Read `TECHNICAL_DEBT_REGISTER.md`'s Infrastructure section specifically, and check whether the Render Postgres expiry date it names has already passed; if it has, confirm what actually happened (was it migrated, upgraded, or did it expire) before assuming anything about Render's current state.
- Do not assume this document, or any of its companions, is still fully accurate. Every one of them was written against a specific, dated snapshot of the platform; verify anything load-bearing against the current codebase and current Azure state before acting on it, exactly as every milestone in this platform's own history has insisted on doing.

## Things that must never be simplified, restated once more because it's the single most important paragraph in this whole handover

Do not let a future deadline pressure a change that makes AI decide an authorization outcome instead of proposing one for human review. Do not let a future convenience feature introduce a live, external-system dependency directly into OPA's evaluation path in a way that makes a decision's determinism depend on network reachability at the moment of evaluation (see `ENTERPRISE_KNOWLEDGE_ARCHITECTURE.md` for how to add exactly this kind of capability without crossing that line). Do not let a future refactor collapse the Authority Graph and Runtime Policies into one concept; they answer different questions and a reviewer needs to be able to ask each one separately. Everything else in this codebase can be improved, replaced, or rewritten as the platform grows; these three cannot be compromised without the platform stopping being what it claims to be.
