# Discovery Playbook

A tactical expansion of `PILOT_PROGRAM_GUIDE.md`'s Discovery stage: the actual questions to ask, in the actual order, and why each one matters. PROPOSED, unvalidated by a real pilot yet.

## Before the first call: what to send ahead

Ask for the prospect's own real authority documentation (a delegation-of-authority memo, an approval matrix, a signing schedule, whatever they actually have, even informal) before the first real conversation, not during it. This does two things: it tests whether real material exists at all (per `PILOT_PROGRAM_GUIDE.md`'s own qualification signal), and it means the first real conversation can be about the document's actual content, not a cold start.

## The conversation, in order

**1. What action, specifically, does the agent take?** Not "AI automation" in general; a specific, named action (approve a purchase order, release a payment, grant a system access). If the answer is vague, the pilot isn't ready to scope yet; ask what the agent will do first, concretely, before anything else.

**2. What does "properly authorized" mean for that exact action, today, without AI involved?** This is the single most important question in Discovery. The answer should map directly onto the uploaded document: a role, a limit, an escalation path. If the customer's own answer doesn't match their own document, that mismatch is itself valuable Discovery output, not a problem to paper over, since Authority Intelligence's own value is partly in surfacing exactly this kind of gap.

**3. What would "unauthorized" look like, concretely?** Ask for a specific, real example of an action that should be denied or escalated, not just what should be allowed. A pilot that can only demonstrate ALLOW decisions hasn't demonstrated authorization at all; per `PILOT_PROGRAM_GUIDE.md`'s Validation stage, a real DENY or HUMAN_REVIEW example is required, and it has to come from somewhere, which is here.

**4. Where does the agent actually run, and who can make it call an external API?** Determines the Integration path (direct signing vs. SDK) and who the pilot's actual technical owner is.

**5. Who reviews and approves things today, and would they be comfortable reviewing an AI-extracted candidate before it becomes a real policy?** Tests organizational readiness for the Authority Intelligence review step, not just technical readiness; a customer whose actual approval culture resists a structured review step will struggle with Deployment regardless of how good the extraction is.

**6. What would make this pilot a clear success, in your own words, before we start?** Ask this explicitly and write the answer down verbatim; it becomes the seed of `CUSTOMER_SUCCESS_METRICS.md`'s customer-specific metrics, and asking it before the pilot starts prevents the goalposts from moving informally later.

## What Discovery is not

Not a sales pitch repeated in call form; the platform's actual capability is already covered by `SALES_ENABLEMENT_PACK.md` before Discovery begins. Not a technical integration planning session; that's Deployment and Integration's job, once Discovery has produced the one artifact everything downstream depends on: a specific action, a specific document, and a specific definition of success, all three in writing, agreed with the customer, before Deployment starts.
