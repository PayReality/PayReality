# Auditor / Assurance Guide

A short, question-and-answer guide for anyone independently verifying what PayReality's records actually show and don't show. For the underlying mechanism, see [SPECIFICATION/13_EVIDENCE_ENGINE.md](SPECIFICATION/13_EVIDENCE_ENGINE.md), [SPECIFICATION/15_USER_JOURNEYS.md](SPECIFICATION/15_USER_JOURNEYS.md) §15.5, and [SPECIFICATION/50_TRUSTED_INTEGRATION_ARCHITECTURE.md](SPECIFICATION/50_TRUSTED_INTEGRATION_ARCHITECTURE.md) §50.14 for the Adapter-mediated case. This guide doesn't repeat the mechanics; it answers the specific questions an audit actually asks.

## Who acted?

The `Agent` named on the Decision's Evidence — a certificate-holding identity whose Ed25519 signature was checked against its registered public key at the moment the request was submitted. Every Agent-direct Decision proves this cryptographically.

## What did they attempt?

The action, amount, currency, counterparty, and resource recorded on the Intent that produced the Decision — exactly what was submitted, signed, and evaluated. Nothing here is reconstructed after the fact.

## Who reported it?

For an agent-direct Decision: the Agent itself, self-reporting. For an Adapter-mediated Decision (the Decision or Receipt will show a non-null `integration` block): the named Trusted Connection, a separately authenticated, customer-controlled identity — check `GetDecisionResponse.integration`/`AuthorizationReceiptResponse.integration` for exactly which one, which System, and which environment.

## What did the organization authorize?

The active `RuntimePolicy` version that matched the request, recorded on the Decision's Evidence — not the policy that happens to be active today. A policy is retrieved by its exact version at the time of the decision, never a live re-lookup.

## What policy applied?

The specific `RuntimePolicy` version id and its compiled bundle hash, both on the Evidence payload. The same version can be independently re-derived and re-verified — the compiled Rego bundle is deterministic, not something you have to take on trust.

## What trusted facts were used?

If the matched policy referenced any Trusted Enterprise Facts, the exact snapshot relied upon — key, value, subject, source, and timestamps — is recorded on the Decision's own Evidence payload. A fact that was missing, expired, or contradicted at decision time never appears as if it had a value; the fail-closed outcome (`HUMAN_REVIEW`) is itself the record of that.

## What Decision occurred?

Exactly one of `ALLOW`, `DENY`, or `HUMAN_REVIEW` — never a fourth value, and immutable once created. If it was `HUMAN_REVIEW`, the original Decision **stays** `HUMAN_REVIEW` forever; the human's later `approved`/`denied` answer lives in a separate `DecisionResolution` record and a second, appended Evidence entry. A resolved review does not overwrite or reclassify the original outcome — if you're checking "what did the system decide" versus "what did a human ultimately approve," these are two different, both-preserved records.

## Which versions existed at the time?

The policy version, and — for an Adapter-mediated Decision — the exact Action Mapping version, Trusted Connection, and Runtime Connection scope, all pinned to what they were at submission. None of these are rewritten later: retiring a mapping, rotating a Trusted Connection's certificate, or resolving a `HUMAN_REVIEW` decision never touches this historical record.

## Can I verify the historical Evidence?

Yes, independently, without asking PayReality to vouch for it: fetch the published Ed25519 public key (`GET /v1/evidence/verification-key` or `/verification-keys` for the full key-rotation history), and check the signature yourself against the Evidence record's own canonical payload. `POST /v1/evidence/{id}/verify` and `GET /v1/evidence/chain/verify` do this same check server-side if you'd rather not implement it yourself, but the point of publishing the key is that you don't have to trust that endpoint either. Note: as of this writing, chain verification requires the caller's own organization credentials — it is not yet a credential-free, public transparency surface.

## What can this Evidence not prove?

- That a downstream external action actually executed. Neither an ALLOW Decision, a consumed Capability Authorization (either runtime path, see below), nor an Authorization Receipt is proof of execution; all three prove an authorization decision was made, never that whatever it authorized actually happened afterward.
- That a Trusted Enterprise Fact was objectively true — only that a specific, registered, authenticated source asserted it.
- That a Trusted Adapter's report corresponds exactly to the real external system's payload — PayReality can and does check *structural* consistency against the approved Action Mapping, but cannot cryptographically reconstruct the original source payload to prove the correspondence.
- That a Capability Authorization token, if issued and consumed, means anything happened downstream. A token is a transport and proof mechanism only. This is true for a token issued from either runtime path: as of Trusted Integration Phase 5, a Capability can be issued for an Adapter-mediated decision too, subject to a live re-check that the underlying Trusted Connection and Runtime Connection are still active, but that re-check is about whether issuance is permitted, not about whether anything downstream later executed.
- That a Runtime Connection's `enforcement_assurance` label (`CAPABILITY_REQUIRED`) means a downstream checkpoint actually requires or checks a Capability. It is the customer's own declared claim about their infrastructure, never independently verified, tested, or observed by PayReality.
- That PayReality itself blocked, gated, or prevented anything. PayReality is a Policy Decision Point: it decides and produces evidence of the decision. Whether a calling system acted on that decision is outside what any PayReality record can attest to.
