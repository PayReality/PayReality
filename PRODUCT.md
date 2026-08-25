# Product

> **This document's positioning language is superseded.** The current, authoritative product positioning is "The Enterprise AI Authority Infrastructure" (three pillars: Authority Intelligence, Runtime Authority, Verifiable Evidence, see `ENTERPRISE_MESSAGING_GUIDE.md` and `SPECIFICATION/01_PRODUCT_OVERVIEW.md`), and the current, verified architectural boundary is documented in `POC_READINESS_REPORT.md`: PayReality is a Policy Decision Point today. It evaluates and determines authorization and produces evidence; it does not itself enforce, block, or execute anything, and no production Policy Enforcement Point exists. This document's "the thing the action has to pass through" framing below predates that explicit boundary and should not be read as a current-state claim. Kept in place as a design-time record, not deleted or rewritten. See `PAYREALITY_FUTURE_VISION.md` for the fuller reasoning behind the boundary.

## What PayReality is

PayReality is **runtime trust infrastructure for autonomous AI agents that take financial actions**. It sits between an AI agent and the action it's about to take, and it answers one question deterministically, every single time: *is this agent actually authorized to do this, right now, under the rules an accountable human approved*, and it produces a signed, tamper-evident record of that answer whether the action was allowed, denied, or kicked to a human.

It is not a dashboard that describes governance. It is the thing the action has to pass through.

## What PayReality is not

- **Not a monitoring or observability tool.** Observability tells you what happened after the fact. PayReality's Decision Engine is in the request path: an Intent doesn't execute until it's been evaluated.
- **Not a policy-authoring UI for its own sake.** The Policy pipeline exists because a human has to approve what an agent can do before an agent can do it, not because policy management is a feature category to check off.
- **Not a general AI-agent orchestration platform.** PayReality doesn't run agents, schedule them, or manage their workflows. It governs the one moment that matters most: the financial action itself.
- **Not (yet) a multi-tenant SaaS with self-service signup.** Today it's a single-tenant deployment per customer, on purpose; see VERSION_3_ROADMAP.md for when and why that changes.

## The five primitives

**Runtime Authority**: an Agent is a certificate-holding identity, acting *for* a Principal (the company or department that actually bears the risk), under Mandates derived from a document a human actually approved. Authority is delegated, scoped, and time-bounded; it is never assumed.

**Policy**: the compiled, versioned, machine-evaluable form of that delegated authority (a Rego bundle evaluated by Open Policy Agent). Exactly one Policy version is active at a time. Activating a new one retires the old one; reactivating an old one *is* the rollback mechanism.

**Runtime Decisions**: every Intent an agent submits is evaluated against the active Policy before anything else happens. The decision is one of three outcomes, never a fourth: `ALLOW`, `DENY`, or `HUMAN_REVIEW`. Anything the system isn't certain about (a timeout, an evaluation error, an undetermined policy result, no active policy at all) resolves to `HUMAN_REVIEW`. The system is built so that *silence and ambiguity can never be mistaken for permission.*

**Evidence**: every Decision, and every later human resolution of a `HUMAN_REVIEW` decision, produces a cryptographically signed record (ED25519, canonical JSON, verifiable independently of this system; see `GET /v1/evidence/verification-key`). Evidence is append-only: a resolved decision gets a *new* Evidence record, not an edited one.

**Assurance** is a live, real-data view of what's actually running: how many agents are registered, what policy is active, how many decisions of each outcome have actually occurred. Not a governance "score" derived from a formula nobody can audit: actual counts, from the actual database.

## How a customer derives value

1. **Before PayReality**: an enterprise either doesn't let its AI agents touch money at all (leaving obvious ROI on the table), or it does, and has no deterministic, provable answer to "what stopped this agent from doing something it shouldn't have" beyond "we trust the model", which is not an answer a CFO, an auditor, or an insurer will accept.
2. **What changes**: every financial action an agent takes passes through a policy that a named human approved, evaluated by a deterministic engine (not a second AI, not another LLM call that could itself hallucinate a yes), with fail-closed behavior on any doubt.
3. **What the customer holds afterward**: a signed Evidence trail for every decision: the artifact that turns "we have a policy" into "we can prove, for this specific transaction, on this date, which mandate authorized it, and here is the cryptographic proof that record hasn't been altered since."
4. **Who that's for, concretely**: a CFO who needs to let agents execute payments without personally re-approving every one; a CISO who needs an enforcement point, not just a logging pipe; an internal auditor who needs individually verifiable records instead of a vendor's dashboard; an insurer who is being asked to underwrite an "AI agent that can move money" risk and has never seen deterministic, signed proof of a control like this before.

## Why deterministic, not another model

The Decision Engine is Open Policy Agent evaluating Rego, not an LLM judging whether an action looks okay. This is a product decision, not an implementation detail: an enterprise cannot audit "the model felt this was fine," and a second AI making the authorization call is the same category of risk as the first, not a control on it. Every ALLOW or DENY this system produces can be re-derived by hand from the active Policy bundle and the Intent that was submitted. That reproducibility is the entire basis for the Evidence being worth anything to an auditor or insurer.

## Enterprise trust, concretely

"Enterprise trust infrastructure" is not a slogan applied after the fact here; it's the filter every feature in this repository was actually built or kept through:

- Fail-closed by construction (`domain/decision/engine.py` has no code path to `ALLOW` except the one explicit success case).
- Immutable decision history (a resolved `HUMAN_REVIEW` decision appends evidence; it never edits the original).
- Independently verifiable evidence (the public key is published; verification doesn't require trusting this server).
- Honest gaps, named as gaps. ARCHITECTURE.md and SECURITY.md name exactly what isn't built yet (human RBAC, key rotation, evidence hash-chaining) rather than implying broader coverage than exists. An enterprise buyer who catches a vendor overclaiming once stops trusting everything else that vendor says, so this repository doesn't overclaim.
