# Enterprise Knowledge Decision Record

A formal architectural-decision-record for Enterprise Knowledge, complementing `ENTERPRISE_KNOWLEDGE_ARCHITECTURE.md`'s narrative design and `ENTERPRISE_DATA_CONNECTOR_STRATEGY.md`'s connector detail. Each decision below states the question, what was decided, what was rejected, and why, in the standard ADR shape, so a future engineer can find the exact tradeoff reasoning without re-reading the full architecture document.

## Decision 1: Facts are resolved before evaluation, never during it

**Question**: should a Runtime Policy referencing an external prerequisite call out to the source system live, at the moment of decision?

**Decision**: no. Every external fact is resolved into a local, versioned store ahead of time (via a connector, `ENTERPRISE_DATA_CONNECTOR_STRATEGY.md`), and Intent evaluation reads only from that local store.

**Rejected**: a live, synchronous call to the external system during evaluation.

**Why**: this platform's entire evaluation model depends on determinism, the same policy and the same input always producing the same decision, reproducibly, later, for an audit. A live call makes the outcome depend on network timing and a third party's availability, at the exact moment this platform's core guarantee matters most.

## Decision 2: The data model is boolean/scalar assertions, not a general knowledge graph

**Question**: how should an external fact be represented internally?

**Decision**: a simple, named assertion (subject, key, value, source, timestamp, expiry, optional attestation).

**Rejected**: a general-purpose knowledge graph modeling facts and their relationships to each other.

**Why**: the actual need is a set of independently-sourced, mostly-boolean-or-scalar facts, each scoped to one subject; the platform already has a real graph model, the Authority Graph, for the one thing that genuinely needs graph structure (delegation and reporting relationships). A second, general-purpose graph for an unrelated problem shape risks becoming its own drifting source of truth, the exact failure mode this design exists to prevent.

## Decision 3: Trust is attestation-first where possible, connector-identity-based otherwise

**Question**: how does the platform know an external fact is genuinely true, not forged or stale?

**Decision**: prefer a cryptographically signed attestation from the source system, verified with the same Ed25519 machinery already used for Agent certificates and Evidence, where the source system can produce one. Where it cannot (the realistic majority case, at least initially), trust rests on the connector's own authenticated, scoped access to the source system, combined with a mandatory expiry on every fact.

**Rejected**: treating every connector-sourced fact as equally trustworthy regardless of whether it's cryptographically attested or not, and omitting expiry as a control.

**Why**: extending this platform's existing signing discipline to external facts, wherever possible, is more consistent with everything else this platform already does than inventing a separate, unrelated trust model. Where attestation isn't available, an explicit, bounded expiry is the honest substitute; it prevents the platform from silently trusting arbitrarily old data forever.

## Decision 4: A stale or missing fact resolves to unknown, which resolves to review, never to a default allow

**Question**: what happens when a policy references a fact the platform doesn't currently have, or only has an expired copy of?

**Decision**: treat it as unknown, and let the platform's existing fail-closed behavior (HUMAN_REVIEW) handle it, exactly as an unreachable OPA instance or a failed signature verification already does.

**Rejected**: falling back to the fact's last-known value indefinitely, or defaulting to a permissive outcome when a fact is missing.

**Why**: this is the same principle (`ENGINEERING_PRINCIPLES.md`: "fail closed, always") applied to a new kind of input; uncertainty about a prerequisite is not the same as the prerequisite being satisfied, and treating it that way would quietly weaken the platform's central guarantee for exactly the class of fact most likely to be stale in practice (external systems change on their own schedule, not the platform's).

## Decision 5: Integration happens through the existing OPA input document, not a new evaluation mechanism

**Question**: how does a resolved Enterprise Knowledge fact actually reach policy evaluation?

**Decision**: attach resolved facts as a new, namespaced section (`enterprise_knowledge`) of the same input document Runtime Authority already assembles (alongside `intent`, `context`, `agent`), and let existing Runtime Policy conditions reference it exactly as they reference any other field.

**Rejected**: a separate evaluation pass, a new policy type, or a different query mechanism specific to Enterprise Knowledge.

**Why**: OPA's own evaluation model does not need to change at all; a condition referencing an Enterprise Knowledge fact is mechanically identical to any other condition. This is the cheapest possible integration in engineering terms and the one least likely to introduce a second, parallel decision-making path a reviewer would need to separately understand.

## Decision 6: Build the first real connector against a real pilot's actual need, not speculatively

**Question**: which enterprise system should the first connector target?

**Decision**: none, yet. The first connector should be built once a real pilot customer's Discovery stage names a specific, real prerequisite blocking their own onboarding.

**Rejected**: building a generic connector framework, or a first connector for one of the seven illustrative examples this milestone named, ahead of any real customer need.

**Why**: this milestone's own guiding principle is to maximize customer learning over speculative feature-building; a connector built against an assumption risks being built for the wrong shape of integration once a real customer's actual system turns out to work differently than assumed.
