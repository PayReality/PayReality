# Declared-vs-Observed Reconciliation: what would be required, and why it isn't built yet

Post-audit implementation (Priority 9): this document exists because the audit found no code
anywhere that compares an Agent's own declared intent against an independently-sourced
observation of the same real-world action, and the follow-up task explicitly asked for this
document instead of an implementation. Read this alongside `INTEGRATION_KIT.md`'s own "Trust
Statement" and `app/domain/canonical_action.py`'s module docstring, which this document doesn't
repeat.

## The current, honest limitation

PayReality's runtime has exactly one attester per request, never two:

- **Agent-direct** (`intent_service.submit_intent`): the Agent's own signed declaration is the
  sole input. Nothing independently checks it against anything else.
- **Adapter-mediated** (`integration_runtime_service.submit_attested_intent`): a trusted
  IntegrationIdentity's attestation *replaces* the Agent's own declaration for that request. The
  Agent is still named (`Intent.agent_id`), but its own account of what it was doing is never
  solicited or compared against the Adapter's.

Both paths are real, tested, and honest about this boundary in their own code comments
(`integration_runtime_service.py`'s own module docstring: *"This does not mathematically prove
the Adapter's own code is bug-free, that it sits on every possible execution path, or that the
external operation ever executed"*). Declared-vs-observed reconciliation would be a genuinely
different, additional capability: **both** an Agent's own declaration **and** an independent
observation of the same event, compared for divergence.

## What evidence would be required to build this safely

A real declared-vs-observed reconciliation needs, at minimum:

1. **Two independently-sourced representations of the same event.** Not the Adapter's
   attestation alone (that's already what exists) -- a genuine second source, e.g. the Agent's own
   signed declaration of what it intended, submitted separately from, and before, the Adapter's
   observation of what actually reached the external system.
2. **A correlation key that ties the two together without letting either side forge it.** The
   two submissions need a shared identifier neither party can unilaterally fabricate after the
   fact -- otherwise "reconciliation" degenerates into "trust whichever one arrives first," which
   is not meaningfully different from today's single-attester model.
3. **A defined divergence policy.** What happens when the declaration and the observation
   disagree? Silently prefer one, escalate to Human Review, deny outright? This is itself an
   authority decision (Runtime Policy's own domain), not a mechanical string-equality check --
   building the comparison without first deciding what a *mismatch* should mean would produce a
   real security-relevant code path with no policy behind it.
4. **A canonical action to compare against, not raw payloads.** `app/domain/canonical_action.py`
   (Priority 3) already gives both sides something structured to converge on -- a prerequisite
   this reconciliation would need, not a component it would need to duplicate.
5. **A threat model for what an Agent gains by lying, specifically.** The Adapter-mediated path
   already assumes the Agent's own account is not authoritative (that's the entire point of
   Trusted Integration). Reconciliation only adds security value if there's a real scenario where
   comparing the two, rather than just trusting the Adapter alone (today's model), catches
   something the Adapter's own trust boundary doesn't already catch.

## Why this is not built in this milestone

- Its incremental security value over the existing single-attester + canonical-action-contract
  model is **unproven**. The Adapter-mediated path was deliberately designed so PayReality does
  not have to trust the Agent's own account at all (see #5 above) -- adding a second,
  independently-solicited declaration is only valuable if a specific attack or failure mode
  requires it, and no such scenario has been identified against a real customer workflow.
- A genuine implementation requires **two** independently sourced representations of the same
  action. Building a comparison against only one (e.g. comparing the Adapter's own attestation
  against itself, or against a value the Agent could still influence indirectly) would be
  misleading machinery -- code that *looks* like independent verification without actually being
  it.
- Choosing a workflow to model this against (which declaration channel, which divergence policy)
  would mean choosing a customer use case this milestone was explicitly told not to choose.

## A future correlation model (proposed, not implemented)

If a real customer's threat model eventually justifies this: an Agent submits a lightweight,
signed **Declared Task Reference** (already a reserved, unused optional field on
`CanonicalAction` -- see `app/domain/canonical_action.py`) at the moment it decides to act, before
any Adapter ever observes anything. The Adapter's later attestation carries the same reference.
`intent_service`/`integration_runtime_service` would resolve both, and a new, explicit Runtime
Policy condition class (`context.reconciliation.declared_task_matched` or similar) would let a
policy author decide what should happen on a mismatch -- deny, escalate, or (for a low-risk action)
proceed regardless. This is a proposal for a future milestone, not a commitment; it is described
here specifically so this milestone's own choice not to build it is a documented decision, not an
oversight.

## Adversarial tests that would determine whether this feature adds real value

Before building any of the above, these are the tests that would actually tell you whether
reconciliation is worth its own complexity, rather than assuming it is:

1. **Can a malicious Agent already achieve its goal through the Adapter-mediated path alone,
   without reconciliation ever detecting it?** If yes for every scenario tried, reconciliation adds
   nothing the Adapter's own trust boundary doesn't already close, and the real gap is in the
   Adapter's own observation fidelity, not in comparing it against the Agent.
2. **Can a compromised or buggy Adapter forge a plausible Declared Task Reference on the Agent's
   behalf?** If the Adapter itself can originate both sides of the comparison, the reconciliation
   is comparing the Adapter against itself, not against an independent source -- a genuine failure
   mode a real design would need to close before shipping, not paper over.
3. **Does a real customer's own workflow ever produce a legitimate declared/observed mismatch
   (e.g. a retried, corrected, or superseded task)?** If mismatches are common in ordinary,
   non-adversarial operation, a naive deny-on-mismatch policy would be a usability regression, not
   a security improvement -- the divergence policy (#3 above) would need real production data to
   design responsibly, not a guess.
4. **Is the marginal engineering cost of building and maintaining a second attestation channel
   smaller than the cost of the specific incidents it would have prevented?** Without a named
   incident class this closes that the canonical-action contract and the existing Adapter trust
   boundary don't already close, this remains a hypothesis, not a justified build.

Until a real design partner's real workflow answers these concretely, this document -- not a
speculative implementation -- is the honest state of this capability.
