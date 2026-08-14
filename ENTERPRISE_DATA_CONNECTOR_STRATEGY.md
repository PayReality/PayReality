# Enterprise Data Connector Strategy

A design, not a build, expanding `ENTERPRISE_KNOWLEDGE_ARCHITECTURE.md`'s connector layer into its own strategy. PROPOSED throughout.

## What a connector is, precisely

A connector is the one piece of code that knows how to talk to a specific external enterprise system (a vendor management system, a compliance platform, an LMS, an ERP) and translate whatever that system exposes into Enterprise Knowledge's own canonical fact shape (subject, key, value, source, timestamp, expiry, optional attestation). A connector never makes a decision, never gets called during Runtime Authority's own evaluation path, and never writes back to the source system. Its only job is keeping the local Enterprise Knowledge store honestly in sync with one external source of truth.

## Connector types, by freshness mechanism

**Event-driven** (preferred, where available): the source system publishes a change event (a webhook, a message queue subscription) whenever a relevant fact changes; the connector consumes it and updates the local store immediately. Freshest possible, and the closest fit to this platform's own existing preference for real-time correctness over polling.

**Scheduled polling** (the honest, realistic default): the connector calls the source system's own read API on a fixed interval (chosen per fact type: an insurance-active flag might poll daily, a budget-available amount might need hourly), and updates the local store on each poll. This is the connector type most enterprise systems will actually support on day one of a real pilot, and this strategy treats it as the normal case, not a fallback to be embarrassed about.

**Attested** (the strongest trust model, adopted wherever a source system can support it): the source system itself produces a signed assertion, verified by the platform using the same Ed25519 verification machinery already used for Agent certificates and Evidence, rather than the platform trusting an unsigned API response. This is the only connector type where the platform's own trust in a fact rests on cryptography rather than on the connector's own network access and the source system's basic availability.

A single connector may combine mechanisms (poll for a baseline, consume events for faster updates in between polls); this strategy does not require picking exactly one per system.

## What a connector must always do, regardless of type

- Stamp every fact with the exact time it was resolved and an explicit expiry, never leave a fact's freshness implicit.
- Fail closed on its own errors: if a connector cannot reach its source system, it does not delete or silently keep serving a stale fact past its expiry; the fact simply ages out and becomes unknown, triggering the same HUMAN_REVIEW path any other missing prerequisite does.
- Never expose write access back to the source system through this integration; a connector is a reader, structurally, not an actor with any ability to change the external system's own state.
- Log every sync (success, failure, and what changed) with enough detail that a security reviewer can answer "when did we last confirm this fact, and from where" without needing to ask engineering.

## Prioritization for a first real connector

**PROPOSED**: build the first connector only once a real pilot customer names a specific prerequisite that actually blocks their own Discovery or Deployment stage (`PILOT_PROGRAM_GUIDE.md`), not speculatively. The seven example prerequisites this milestone names (vendor approval, AML, insurance, training, risk acceptability, budget, delegation validity) each plausibly live in a different kind of system (a vendor management tool, a compliance platform, an insurance system, an LMS, a risk-scoring tool, an ERP/finance system, and the platform's own Authority Graph respectively), and building a generic connector framework before knowing which one a real customer actually needs first risks over-engineering for a case that never arrives in that shape.

**One exception worth naming explicitly**: "delegation valid" does not need an external connector at all. It is already answerable from data this platform owns directly, the Authority Graph itself. This is worth stating plainly so a future team doesn't accidentally build external-connector machinery for a fact the platform can already answer internally.

## Security posture

A connector's own credentials to an external system (an API key, an OAuth token) belong in the same Key Vault, Managed-Identity-first model every other secret in this platform already uses, never a new, separately-managed credential store. A connector should hold the minimum external permission it needs (read-only, scoped to exactly the facts it's responsible for), matching this platform's own RBAC discipline of least-privilege by default (`ENGINEERING_PRINCIPLES.md`).

## Multi-tenancy

Every connector instance and every fact it resolves is organization-scoped, exactly like every other tenant-owned resource in this platform (`ENGINEERING_PRINCIPLES.md`'s multi-tenancy conventions apply here without modification): a connector configured for one organization's vendor management system must never resolve or expose facts to a different organization, and the Enterprise Knowledge store's own schema should carry `organization_id` from its very first migration, not retrofit it later the way several earlier subsystems in this platform's own history had to.
