# Part 1 — Product Overview

**Supersedes/synthesizes:** `README.md`, `PRODUCT.md`, `PLATFORM_POSITIONING.md`, `PAYREALITY_MASTER_BLUEPRINT.md`. Corrects known staleness in those documents: RBAC, evidence key rotation, and evidence chaining are described there as future gaps; all three are implemented and live (see [14_SECURITY_MODEL.md](14_SECURITY_MODEL.md), [13_EVIDENCE_ENGINE.md](13_EVIDENCE_ENGINE.md)).

## 1.1 What PayReality is

PayReality is **runtime trust infrastructure for autonomous AI agents that take financial actions.** It sits between an AI agent and the action it is about to take, and answers one question, deterministically, every time: *is this agent actually authorized to do this, right now, under rules an accountable human approved* — and it produces a signed, tamper-evident record of that answer regardless of whether the action was allowed, denied, or escalated to a human.

It is not a dashboard that describes governance after the fact. It is the thing the action has to pass through. The Decision Engine is in the request path — an Intent an agent submits does not execute until it has been evaluated against the currently active policy.

## 1.2 What PayReality is not

- **Not a monitoring or observability tool.** Observability describes what already happened. PayReality evaluates and decides before the action, not after, and produces evidence before execution. It is a Policy Decision Point, not a Policy Enforcement Point: it does not itself block or execute anything, and no production Policy Enforcement Point exists yet (see the Glossary).
- **Not a policy-authoring UI for its own sake.** The authoring pipeline (Runtime Policy Studio, AI Authority Builder, AI Policy Builder) exists because a human must approve what an agent can do before the agent can do it. Authoring is instrumental to the authorization decision PayReality makes, not a feature category on its own.
- **Not a general AI-agent orchestration platform.** PayReality does not run agents, schedule them, or manage their workflows. It governs one moment: the financial action itself, and the authority behind it.
- **Not a multi-tenant, self-service SaaS today.** The schema has an `Organization` concept and Phase 10 added real per-user roles, but routing assumes a single bootstrapped organisation per deployment (see [08_RUNTIME_AUTHORITY.md](08_RUNTIME_AUTHORITY.md) §"Single-tenant today, multi-tenant-shaped schema" and [16_CURRENT_LIMITATIONS.md](16_CURRENT_LIMITATIONS.md)).

## 1.3 The five core primitives

These five concepts recur through every part of this specification; they are the platform's actual vocabulary, not marketing terms.

| Primitive | Definition |
|---|---|
| **Agent** | A certificate-holding identity, acting *for* a Principal (the person, team, or org that bears the risk), that submits signed Intents. Has a full lifecycle (registered → active → suspended/revoked/retired). See [11_AGENT_ARCHITECTURE.md](11_AGENT_ARCHITECTURE.md). |
| **Authority** | The delegated, scoped, time-bounded right to act, whether expressed as a legacy Mandate (retired pipeline, see [17_LEGACY_COMPONENTS.md](17_LEGACY_COMPONENTS.md)) or as the current Authority Model's `AuthorityRelationship` graph plus Runtime Authority Context (see [08_RUNTIME_AUTHORITY.md](08_RUNTIME_AUTHORITY.md)). Authority is never assumed; it is either on record or absent. |
| **Runtime Policy** | The compiled, versioned, machine-evaluable form of approved authority: a Rego bundle evaluated by Open Policy Agent (OPA). Exactly one *set* of active policies exists at a time; publishing a new version deploys the full active set fresh (see [07_RUNTIME_POLICY_ENGINE.md](07_RUNTIME_POLICY_ENGINE.md)). |
| **Decision** | The outcome of evaluating one Intent against the active policy set: `ALLOW`, `DENY`, or `HUMAN_REVIEW` — never a fourth value. Anything the system is not certain about (timeout, evaluation error, no covering policy) resolves to `HUMAN_REVIEW`. See [12_DECISION_ENGINE.md](12_DECISION_ENGINE.md). |
| **Evidence** | An ED25519-signed, append-only record of a Decision (and of any later human resolution of a `HUMAN_REVIEW`). Since Phase 5, Evidence records are also hash-chained per organisation, so a deleted or reordered record is independently detectable, not just a tampered one. See [13_EVIDENCE_ENGINE.md](13_EVIDENCE_ENGINE.md). |

A sixth term, **Assurance**, names the live read of what's actually running — agent counts, active policy, decision volume by outcome — computed from the same database as everything else, not a separately-maintained "governance score."

## 1.4 How a decision actually happens, end to end

1. An **Agent** submits an **Intent** (e.g. "pay $42,000 to vendor X"), signed with its Certificate's private key, which never leaves wherever it was generated — PayReality never holds a private key for any agent (see [11_AGENT_ARCHITECTURE.md](11_AGENT_ARCHITECTURE.md) §Certificates).
2. The request is authenticated (`verify_agent_signature`) and the Decision Engine resolves the acting Principal, builds an **OPA input document** — `{"intent": {...}, "context": {...}, "agent": {...}}` — enriching `context.authority` with a live-resolved Runtime Authority Context (organisation/department/team/role/risk band/active delegations; see [08_RUNTIME_AUTHORITY.md](08_RUNTIME_AUTHORITY.md)), and queries the currently active Rego bundle.
3. OPA returns `allow`, `deny`, or nothing decisive. Anything not explicitly `allow` resolves to `HUMAN_REVIEW`. This is fail-closed by construction: an OPA timeout, an OPA error, or no policy covering the intent's scope all also resolve to `HUMAN_REVIEW`, never `ALLOW`.
4. An **Evidence** record is signed and stored, chained to the immediately preceding Evidence record in the same organisation's scope. A `HUMAN_REVIEW` decision that is later approved or denied appends a *second* Evidence record; the original Decision row is never mutated.
5. **Assurance** reads real counts and real recent Decisions from the same database live, on every request.

## 1.5 How a customer derives value

1. **Before PayReality:** an enterprise either doesn't let its AI agents touch money at all (leaving ROI on the table), or does, with no deterministic, provable answer to "what stopped this agent from doing something it shouldn't have" beyond "we trust the model" — not an answer a CFO, auditor, or insurer accepts.
2. **What changes:** every financial action an agent attempts passes through a policy a named human approved, evaluated by a deterministic engine (OPA/Rego, not a second LLM that could itself hallucinate a "yes"), fail-closed on any doubt.
3. **What the customer holds afterward:** a signed, chained Evidence trail — the artifact that turns "we have a policy" into "we can prove, for this specific transaction, on this date, exactly which authority permitted it, and that the record hasn't been altered or removed since."
4. **Who this is for, concretely:** a CFO who needs agents to execute payments without personally re-approving every one; a CISO who needs a real decision made before the action happens, not another logging pipe; an internal auditor who needs individually verifiable records instead of a vendor dashboard; an insurer being asked to underwrite "an AI agent that can move money" who has never seen deterministic, signed proof of a control like this.

## 1.6 Why deterministic evaluation, not another model

The Decision Engine is Open Policy Agent evaluating Rego — not an LLM judging whether an action looks reasonable. This is a product decision, not an implementation detail: an enterprise cannot audit "the model felt this was fine," and a second AI making the authorization call is the same category of risk as the first agent, not a control on it. Every `ALLOW`/`DENY` this system produces can be re-derived by hand from the active Rego bundle and the submitted Intent. That reproducibility is the entire basis for Evidence being worth anything to an auditor or insurer. (Where AI *is* used — the AI Authority Builder and AI Policy Builder, Parts 9–10 — its output is always a human-reviewable *draft*, never a live enforcement decision; see [16_CURRENT_LIMITATIONS.md](16_CURRENT_LIMITATIONS.md) for exactly where that AI-generated content is and isn't yet independently verified for correctness.)

## 1.7 Enterprise trust, concretely — what's actually true today

"Enterprise trust infrastructure" is the filter every surviving feature in this repository was built or kept through. As of this specification:

| Claim | Status |
|---|---|
| Fail-closed by construction | **True.** `domain/decision/engine.py` has exactly one code path to `ALLOW`; every other path (timeout, error, no covering policy, ambiguous result) resolves to `HUMAN_REVIEW`. |
| Immutable decision history | **True.** A resolved `HUMAN_REVIEW` decision appends a new Evidence record; the Decision row and prior Evidence are never edited. |
| Independently verifiable evidence | **True**, and stronger than originally built: `GET /v1/evidence/verification-key` publishes the current key, `GET /v1/evidence/verification-keys` publishes the full rotation history so a record signed under a retired key is still independently verifiable, and `GET /v1/evidence/chain/verify` verifies both signature validity and chain continuity per organisation. |
| Real per-user roles and permissions (RBAC) | **True as of Phase 10.** Six roles (`owner`, `governance_admin`, `agent_admin`, `reviewer`, `auditor`, `executive`), enforced by permission (not role identity) at every mutating endpoint. See [14_SECURITY_MODEL.md](14_SECURITY_MODEL.md). |
| Evidence hash-chaining | **True as of Phase 5.** Superseded the earlier stated gap. |
| Agent-scoped policy narrowing (Scope.agent) | **True as of Milestone 17.1.** A Runtime Policy authored to apply only to one Agent previously matched every agent identically, because the OPA input never carried a real agent id. `build_opa_input`/`evaluate` now take an explicit `agent_id` keyword argument, so the policy correctly discriminates between the intended agent and any other. |
| Honest gaps, named as gaps | **Still the operating principle** — see [16_CURRENT_LIMITATIONS.md](16_CURRENT_LIMITATIONS.md) for what remains actually unbuilt or unverified today (AI provider integrations on the hosted demo are fake/simulated; the SDK ships with a shared admin key; several live SDK/Deploy paths are unverified end-to-end). |

## 1.8 The one-sentence version, for each audience

- **For a CFO:** "Agents can move money only inside limits you approved, and every attempt — allowed or not — leaves a signed, unforgeable receipt."
- **For a CISO:** "A real authorization decision made in the request path before every attempt, not a log you review after the fact; deterministic, not another model's opinion."
- **For an auditor/insurer:** "Every decision is reproducible by hand from the policy and the request; the record of it is cryptographically chained so a deletion or edit is detectable, not just a forgery."
- **For an engineer joining the project:** "FastAPI + PostgreSQL + Open Policy Agent, a compiler that turns human-approved authority into Rego, and a signing/chaining layer around every decision it produces." See [02_SYSTEM_ARCHITECTURE.md](02_SYSTEM_ARCHITECTURE.md) next.
