# Discovery Validation Ledger

**Purpose**: prior audits have twice reached incorrect blanket conclusions about customer discovery, first that zero real customer-discovery conversations exist anywhere in the repository, later that a specific named conversation (Dehan) is documented when in fact only a single passing sentence about it exists. Both errors happened because "discovery has occurred" is not one fact, it is several distinct, independently verifiable claims, and a document that is true about one of them (a contact was made) says nothing about the others (a transcript exists, findings were documented, a POC was discussed, a POC was confirmed). This ledger exists so a future audit checks each stage independently, against real repository evidence, rather than inferring a later stage from an earlier one, or inferring that nothing happened because the most detailed stage hasn't happened.

## The six stages, and the rule for using them

1. **CONTACTED**: a real, named external party was reached (an email sent or received, a briefing document exchanged, a call scheduled), with some artifact of that contact locatable in this repository or explicitly cited from outside it.
2. **MEETING HELD**: a live conversation (call, in-person meeting, or workshop) actually took place, not merely that contact was made.
3. **TRANSCRIPT AVAILABLE**: a transcript, recording, or contemporaneous notes of that meeting exist and are locatable, in this repository or explicitly referenced from a specific external location.
4. **FINDINGS DOCUMENTED**: specific, attributable findings from that meeting have been written down and cited back to their source, the way `GAVIN_ABSA_PRODUCT_AUDIT.md` cites specific claims from the ABSA briefing.
5. **POC DISCUSSION**: a proof-of-concept engagement was actually discussed with the external party, not merely that PayReality's own internal materials describe hypothetical POC readiness.
6. **POC CONFIRMED**: the external party has actually agreed to run a POC, with some documented confirmation (an email, a signed document, a dated commitment).

**The rule**: mark each stage only from direct evidence for that specific stage. A later stage's existence is never assumed from an earlier stage's existence, and an earlier stage is never assumed absent just because a later stage hasn't happened yet or its evidence hasn't been located. If evidence for a stage cannot be found, mark it "NOT DOCUMENTED," not "NO," since the correct claim is about what this repository currently shows, not a claim that the event definitely never happened outside it.

## Current ledger

| Party | Contacted | Meeting held | Transcript available | Findings documented | POC discussion | POC confirmed |
|---|---|---|---|---|---|---|
| Gavin / ABSA | YES. `GAVIN_ABSA_PRODUCT_AUDIT.md` line 7: "the ABSA briefing is a contract already sent to a real prospect." A real briefing document was exchanged. | NOT INDEPENDENTLY DOCUMENTED. No calendar record, call log, or meeting note exists in this repository; the briefing document's existence does not by itself establish a live meeting took place. | NO. No transcript or recording exists in this repository. | YES, but only relative to the briefing document, not a meeting transcript. `GAVIN_ABSA_PRODUCT_AUDIT.md` and `GAVIN_REMEDIATION_PLAN.md` cite specific, checkable claims from the briefing and map each to real code. | IMPLIED BY CONTEXT, NOT DOCUMENTED AS A DISTINCT EVENT. The briefing's own content (an integration pattern, a threshold-change example, a proposed pipeline) reads as POC-scoping material, but no document explicitly records "a POC was discussed with Gavin/ABSA" as its own dated fact. | NOT DOCUMENTED. No repository evidence of a signed or confirmed POC commitment from ABSA. |
| Dehan Scherman | NOT INDEPENDENTLY DOCUMENTED. The only textual basis is one sentence in `PAYREALITY_FUTURE_VISION.md` line 34 referring to "two enterprise interviews (Gavin, Dehan)"; no contact artifact (email, invite, log) exists in either repository. | ASSERTED BY ONE SENTENCE, NOT INDEPENDENTLY DOCUMENTED. See `DEHAN_SCHERMAN_DISCOVERY_RECORD.md`. | NO. | NO. Only a one-line interpretive gloss exists ("both nudge toward the former"), not a findings record attributable to specific statements. | NOT DOCUMENTED. | NOT DOCUMENTED. |

## How to use this ledger going forward

When a new external discovery contact happens (a call, a briefing, an interview), add a row here the same day, marking only the stages that already have real evidence, and add source material (notes, transcript, or a dated summary) to the repository before marking "Findings documented" for that party. When an existing row's status changes, for example a transcript is later added for an already-contacted party, update only that cell and its supporting citation; do not retroactively upgrade other cells based on the new evidence unless that evidence actually speaks to them.

Do not delete a row or a historical status once recorded, even if a later stage is reached; the history of how discovery actually progressed (contact first, meeting later, transcript sometimes never) is itself useful and should remain visible, not overwritten.
