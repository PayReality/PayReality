# Website Claims

The compact, ready-to-use extract for the next website milestone. Every claim here is derived from, and must stay consistent with, [ENTERPRISE_MESSAGING_GUIDE.md](ENTERPRISE_MESSAGING_GUIDE.md) — that document is the deeper source of truth, including the reasoning and the full VERIFIED/INFERRED/PROPOSED labeling; this one is the short list a copywriter or designer actually needs open while working. If the two ever disagree after a future edit, the Messaging Guide wins and this file needs updating, not the other way around.

## Approved homepage claims

- **Category**: "The Enterprise AI Authority Infrastructure."
- **One-sentence description**: "PayReality is the Enterprise AI Authority Infrastructure: it decides, before an AI agent acts, whether that agent actually has the authority to take the action, and produces a cryptographically signed record of the decision."
- "PayReality evaluates proposed AI actions against organizational authority before execution."
- "Every decision produces a signed, independently verifiable record — Evidence, and, for a specific decision, an Authorization Receipt that packages it for a human reader."
- "Organizations should determine what autonomous systems are authorized to do — not the autonomous system itself."
- "A customer-controlled Trusted Adapter can report a real enterprise operation to Runtime Authority through a deterministic, human-approved mapping — an independent, corroborating signal alongside the agent's own authenticated request."

## Safe product descriptions

- Three pillars: **Authority Intelligence** (turns governance documents into structured, human-reviewed candidate authority data), **Runtime Authority** (the deterministic ALLOW/DENY/HUMAN_REVIEW decision engine), **Verifiable Evidence** (every decision's signed, independently checkable record).
- Two runtime paths, both real and supported today: an agent submitting its own signed, authenticated request directly; and a customer's Trusted Adapter independently reporting a real operation through an approved Action Mapping. The second strengthens the first; neither replaces it.
- Deterministic, not probabilistic: policy evaluation runs on a real, embedded Open Policy Agent instance, never a language model at decision time.

## Safe runtime claims

- "Evaluated before execution" — accurate for PayReality's own step. Never extend this into "and therefore the action cannot proceed without PayReality's approval" — whether a calling system actually waits for and respects the answer is up to that system, not something PayReality itself enforces today.
- "Fail-closed by design" — any ambiguity, timeout, missing fact, or unrecognized situation resolves to `HUMAN_REVIEW`, never a default `ALLOW`.
- "An explicit, human-approved allow-list, never 'all agents'" — true of Runtime Connections specifically; there is no "represent all current and future agents" option anywhere in the system.
- "For an ALLOW decision, PayReality can issue a short-lived, single-use Capability Authorization token", true on either runtime path; never state or imply this is itself enforcement, only that a downstream system could choose to require it.

## Safe Evidence claims

- "Independently verifiable, without asking PayReality to vouch for it" — the signing key is published; verification is a real cryptographic check against a customer's or auditor's own tooling.
- "An Authorization Receipt packages one decision's Evidence, authority, and provenance into one shareable view." Never claim it is a second or stronger proof than Evidence, and never that it proves a downstream action executed.
- "Historical provenance stays pinned" — a decision's policy version, mapping version, and connection scope are exactly what they were at the moment of the decision, never rewritten by a later resolution, rotation, or retirement.

## Prohibited / overstated wording

Never use any of the following as an unqualified, present-tense platform claim (see [ENTERPRISE_MESSAGING_GUIDE.md](ENTERPRISE_MESSAGING_GUIDE.md) §16 for the full list and the reasoning behind each):

- "PayReality blocks all unauthorized AI actions" / "prevents AI from executing" / "cannot execute without PayReality" / "non-bypassable."
- "The Trusted Adapter gives the Agent authority," "proves the external operation occurred," or "PayReality trusts the Agent because an Adapter exists."
- Capability Authorization for a Trusted-Adapter-reported decision described as itself enforcement, or as proof of anything beyond what the underlying Decision already established.
- A customer's own `CAPABILITY_REQUIRED` declaration on a Runtime Connection described as independently verified or enforced by PayReality; it is the customer's own unverified claim about their infrastructure.
- "PayReality secretly watches enterprise systems" or anything implying PayReality itself has access to a customer's systems — the Adapter is customer-controlled, customer-hosted infrastructure.
- Vendor-named connectors ("works with SAP," "integrates with Workday") — no vendor-specific connector ships with the platform; every Adapter is customer-built.
- "Automatic discovery" of what an external operation means — every Action Mapping is hand-authored and human-approved.
- Any named customer, pilot, logo, or case study that doesn't genuinely, verifiably exist yet.
- Any SOC 2, uptime, or SLA claim that hasn't actually been measured or completed.
- "AI decides our authority rules" in any form — a human always promotes and approves; AI only proposes candidates with full provenance.

## Current vs. future, stated plainly

| Live today | Future, state the condition every time |
|---|---|
| Agent-direct runtime path | A real downstream enforcement point (PEP) requiring PayReality's decision before acting — none exists for any customer |
| Trusted-Adapter-mediated runtime path, full lifecycle | Verified or registered-external-PEP enforcement assurance; no distinct external-checkpoint trust registration exists |
| Capability Authorization, for an ALLOW decision on either runtime path | Vendor-specific Adapter connectors (SAP, Workday, etc.) |
| Signed, verifiable Evidence and Authorization Receipt | Automatic discovery of external operations/schemas |
| Trusted Enterprise Facts, fail-closed on absence/conflict | Mapping-drift monitoring |
| Authority Intelligence (human-gated candidate proposals) | Full self-host / dedicated-instance productization |
| Multi-tenant, data-layer-isolated, live-tested | On-premises deployment |
