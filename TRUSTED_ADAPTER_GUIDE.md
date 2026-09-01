# The Trusted Adapter, Explained

A plain-English companion to [SPECIFICATION/50_TRUSTED_INTEGRATION_ARCHITECTURE.md](SPECIFICATION/50_TRUSTED_INTEGRATION_ARCHITECTURE.md), which has the full technical account. This document is the one to hand a customer admin, a prospect's security reviewer, or anyone writing website/sales copy who needs the honest answer in one place.

## The three questions, kept separate

Every answer below comes back to the same three, deliberately distinct questions:

- **Agent** — who is acting?
- **Trusted Adapter** — what company-controlled component is attesting what action is being attempted?
- **PayReality** — does the organization authorize that Agent to perform that action under these conditions?

The Adapter never answers the third question. PayReality still, and only, decides authorization.

## What is the Adapter?

A small, customer-built (or customer-deployed) component that observes a real operation happening against one of the customer's own enterprise systems, and reports it to PayReality using a meaning the organization has already approved.

## Where does it run?

**Inside the customer's own environment.** It is the customer's infrastructure, the customer's responsibility, running under the customer's own network and access controls — the same way an Agent's own private signing key never leaves the customer's environment. PayReality does not host it, does not have standing access to it, and has no visibility into the enterprise system it observes beyond exactly what the Adapter chooses to send.

## Why does it exist?

Without it, PayReality only ever has an Agent's own self-reported description of what it's about to do. That's a real, useful, cryptographically authenticated statement — but it's also self-reported. The Adapter adds a second, independent, customer-controlled party that can corroborate what's actually happening against a real system, for organizations that want that stronger signal. It is additive: an organization that doesn't need it keeps using the agent-direct path exactly as before.

## What does it observe?

Only what the customer's own integration code chooses to expose it to. PayReality has no say in this and no visibility beyond it.

## What does it send to PayReality?

A signed, structured request naming: which Trusted Connection it is, which Runtime Connection (environment + approved mapping + allowed Agents) it's using, which Agent it's reporting on behalf of, the external system's own operation name, the canonical action that operation means, and only the specific fields the organization's own Action Mapping declared should be extracted — resource, amount, currency, and so on. Nothing outside that pre-approved shape is ever treated as trustworthy input to a decision.

## How is it authenticated?

The same class of mechanism as an Agent: an Ed25519 keypair, generated once and shown exactly one time during registration, never persisted by PayReality's servers. Every request the Adapter sends is signed with that key and checked against its own, separately registered identity (a "Trusted Connection") — never against an Agent's own certificate.

## Which Agents can it represent?

Only the ones an admin has explicitly, individually allow-listed on the specific Runtime Connection it's using. There is no "represent any Agent" or "represent all current and future Agents" option anywhere in the system — the allow-list is enumerated, one Agent at a time, and checked on every single request.

## What happens if it names an unapproved Agent?

The request is rejected before it ever reaches an authorization decision — no Decision row is created, no Evidence is produced, because nothing was evaluated. This is called an **integration rejection**, and it's categorically different from a `DENY`: a `DENY` means PayReality evaluated a legitimate request and said no; an integration rejection means PayReality never had a legitimate request to evaluate in the first place.

## Does PayReality host the Adapter?

No. See "Where does it run?" above. There is no PayReality-hosted or PayReality-managed Adapter deployment option today.

## Does the Adapter make authority decisions?

No. It reports what it observed. PayReality's Runtime Authority is the only thing that decides whether the organization authorizes the action — exactly the same decision engine, the same policies, the same ALLOW/DENY/HUMAN_REVIEW outcomes as the agent-direct path.

## Is the Adapter a PEP (Policy Enforcement Point)?

No. Nothing in this architecture reaches out to, blocks, or enforces anything against the customer's enterprise system. The Adapter reports; PayReality decides; whether anything downstream actually acts on that decision is entirely up to the customer's own systems today. See [ENTERPRISE_MESSAGING_GUIDE.md](ENTERPRISE_MESSAGING_GUIDE.md) §6 for the full PDP/PEP boundary, which applies here without exception.

## Does the Adapter guarantee downstream enforcement?

No. Nothing in the current architecture does, on either the agent-direct or the Adapter-mediated path. This is a real, named, honestly-disclosed boundary — not a hidden gap.

For an ALLOW decision on either path, PayReality can issue a short-lived, single-use Capability Authorization token, and a customer can even declare, on a given Runtime Connection, that their own downstream checkpoint requires one (see the next question). But a declaration is not a guarantee: PayReality never independently verifies that any checkpoint actually enforces it, and issuing or consuming a Capability is never proof the downstream action executed.

## What happens if my orchestration code requests a Capability twice for the same Decision?

As of Trusted Integration Phase 5.1, it is rejected, not duplicated: one Decision produces at most one currently usable Capability, ever, enforced by a real database constraint (`capability_tokens.decision_id` is unique), not merely a check in application code that a race could slip past. A retry while the first Capability is still valid gets `409 capability_already_issued`; a retry after the first was already consumed gets `409 capability_already_consumed_for_decision`; a retry after the first expired unconsumed gets `409 capability_expired_not_renewed` — the last of these is deliberate: PayReality does not silently mint a fresh Capability for a lapsed authorization on the assumption that nothing changed, since authority conditions may have. If your integration genuinely needs to retry a lapsed authorization, that requires a new authorization event on PayReality's side (a fresh Decision, or, for a `HUMAN_REVIEW` decision, no automatic path exists today — see [50_TRUSTED_INTEGRATION_ARCHITECTURE.md](SPECIFICATION/50_TRUSTED_INTEGRATION_ARCHITECTURE.md)), not something to work around by calling the issuance endpoint again.

## Can I request a Capability for a decision my reviewer approved after Runtime Authority sent it to human review?

Yes, via `POST /v1/decisions/{id}/capability-token/from-review` (or the SDK's `agent.request_capability_from_review()`), once the `HUMAN_REVIEW` decision has an `approved` resolution. The original Decision itself is never rewritten to `ALLOW` — it still reads `HUMAN_REVIEW` — this issues a separate, linked Capability authorizing continuation of that specific business operation. It shares every live status re-check and the same one-Capability-per-Decision guarantee described above.

## Can I require a Capability before my checkpoint acts?

You can *declare* that requirement on a Runtime Connection, by setting its `enforcement_assurance` to `CAPABILITY_REQUIRED` (the default is `ADVISORY`, meaning no declared requirement). This is your own claim about your own infrastructure, recorded so it's visible on the Runtime Connection, never something PayReality tests, observes, or enforces on your behalf. Two further labels sometimes discussed in this platform's longer-term plans, a registered external checkpoint and an independently verified one, do not exist today: no code path can set them, because doing so honestly would require PayReality to register and authenticate your checkpoint as its own trusted identity, which this phase does not build.

## What does the Adapter *not* prove?

It does not mathematically prove its own code is bug-free, that it sits on every possible path an enterprise operation could take, or that the external operation it reported actually, physically completed. It attests what it observed, structurally checked against an approved mapping — a real, useful, but bounded guarantee, never an absolute one.
