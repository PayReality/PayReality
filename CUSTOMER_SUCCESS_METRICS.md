# Customer Success Metrics

Expands `PILOT_PROGRAM_GUIDE.md`'s Success Metrics section with the specific measurement approach for each metric, not just the metric name. PROPOSED, unvalidated by a real pilot yet.

## The four baseline metrics every pilot tracks, and how to actually measure each

**Time from document upload to a reviewable Authority Graph.** Measurement: timestamp the corpus upload call, timestamp when the customer's own reviewer first opens the resulting Authority Graph review screen. This is a direct, unambiguous measure of Authority Intelligence's real value and requires no subjective judgment from either side.

**Time from policy draft to activation.** Measurement: timestamp the candidate's promotion into a draft policy, timestamp its activation. This measures whether the review/approve/activate lifecycle fits the customer's actual governance cadence; a very long gap here is itself a finding worth discussing with the customer directly, not a metric to quietly bury.

**Decision accuracy against the customer's own expected outcome.** Measurement: for every real Intent submitted during Validation, the customer's own domain expert states in advance (or immediately after, before seeing the result, if in advance isn't practical) what they expect the outcome to be, and the two are compared afterward. This must be judged by the customer, not by PayReality, since the entire point is whether the platform matches the customer's own authority structure, not PayReality's interpretation of it.

**Independent Evidence verification success.** Measurement: binary, the customer's own team runs the verification themselves, using the published mechanism, without PayReality doing it for them. This is the one metric in this whole document that should never be reported as "we verified it for them"; if PayReality performs the verification instead of the customer, this metric hasn't actually been measured at all.

## Metrics specific to each pilot, from Discovery

`DISCOVERY_PLAYBOOK.md`'s Question 6 produces a customer-stated definition of success before the pilot starts. Record it verbatim in the Discovery document and treat it as a fifth metric, specific to that pilot, tracked with the same rigor as the four baseline metrics above. A pilot that meets the four baseline metrics but misses the customer's own stated goal has not succeeded, regardless of how the baseline numbers look.

## What counts as a genuinely successful pilot, stated plainly

All four baseline metrics measured (not assumed), the pilot-specific metric from Discovery met, and both the technical and business stakeholders from the original workshop confirming, in the Review stage (`PILOT_EXECUTION_GUIDE.md`), that the pilot did what they came for. Any one of these missing means the pilot is not yet ready for the Expansion conversation, regardless of how the rest looks.

## What this document deliberately does not include

A numeric target (a specific number of milliseconds, a specific percentage accuracy) for any metric. Per `LAUNCH_READINESS_REPORT.md`'s own finding, no pilot has run yet to establish what a realistic target even looks like; publishing an invented target now would repeat the exact mistake this whole engagement has worked to avoid, stating a number as fact before it has been measured even once.
