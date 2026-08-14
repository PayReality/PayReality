# Pilot Execution Guide

The operational companion to `PILOT_PROGRAM_GUIDE.md` (Milestone 8), which defined the eight-stage process (Qualification through Reference Customer). This guide is for whoever is actually running a pilot day to day: what to do, in what order, with what artifact, at each stage. PROPOSED throughout; no pilot has run yet to validate this against, per `PILOT_PROGRAM_GUIDE.md`'s own honest framing, carried forward here.

## Before Qualification: what "an existing conversation" needs before it becomes a pilot

Per this milestone's own Workstream 4 framing ("turn the existing conversations into structured pilots"): a conversation becomes a pilot candidate the moment it can answer `PILOT_PROGRAM_GUIDE.md`'s own qualification questions with real, specific answers, not general interest. Until then, it is a lead, not a pilot, and should not be run through Deployment steps prematurely. This distinction matters operationally: the single biggest risk to a first pilot is skipping straight to Deployment because momentum feels good, before Discovery has actually produced the one artifact everything else depends on (see below).

## The one artifact everything else depends on

Discovery's real output (per `PILOT_PROGRAM_GUIDE.md` and `DISCOVERY_PLAYBOOK.md`) is the customer's actual authority documents and one real, named scenario. Do not proceed to Deployment without both in hand. A pilot that begins integration work before Authority Intelligence has anything real to process is building on an assumption, not a customer's actual authority structure.

## Stage-by-stage execution checklist

**Qualification**: run the five questions in `PILOT_PROGRAM_GUIDE.md` Section 1 as a real, written scorecard, not an impression. A prospect who can't answer at least three of the five concretely is not ready for Discovery yet; keep them warm, don't force the process.

**Discovery**: run `DISCOVERY_PLAYBOOK.md` in full. Output: the written Discovery document `PILOT_PROGRAM_GUIDE.md` already specifies (the specific action, the specific document, the specific success metrics, the explicit non-goal list).

**Workshop** (new in this milestone, sits inside Discovery): run `ENTERPRISE_WORKSHOP_TEMPLATE.md` as the structured session that actually produces the Discovery document, rather than treating Discovery as a series of unstructured calls. One real workshop, with the right people in the room, produces a better Discovery document faster than several loosely-scoped calls.

**Deployment**: follow `PILOT_PROGRAM_GUIDE.md` Section 3's five real steps in order (organization created, owner claimed, corpus uploaded, policy activated, agent registered and activated). Do not skip ahead to Integration before a policy is actually active; an agent with nothing to be evaluated against isn't testing anything.

**Integration**: follow `PILOT_PROGRAM_GUIDE.md` Section 4. Default to the Python SDK unless the customer's own technical owner has a specific reason to sign Intents directly.

**Validation**: follow `PILOT_PROGRAM_GUIDE.md` Section 5's four checks. The independent Evidence verification check is non-negotiable; a pilot that never asks the customer to verify a signed record independently hasn't actually demonstrated the platform's central differentiator.

**Review**: a structured checkpoint (new in this milestone) at the end of Validation, before Expansion: walk through `CUSTOMER_SUCCESS_METRICS.md`'s metrics with the customer directly, in writing, and get an explicit yes/no on whether the pilot's own stated goals (from the Discovery document) were met. Do not let this become informal or assumed from silence.

**Expansion**: follow `PILOT_PROGRAM_GUIDE.md` Section 7's criteria exactly; do not expand scope based on enthusiasm alone if the actual metrics from Review are mixed.

**Reference Customer**: follow `PILOT_PROGRAM_GUIDE.md` Section 8. Permission to reference is always a separate, explicit ask, never assumed from a successful pilot.

## What to do when a pilot surfaces a real platform gap

Per this milestone's own rule ("avoid major feature development unless a pilot uncovers a critical issue"): a gap found during a real pilot is handled differently from a speculative feature request. Distinguish, in writing, whether the gap blocks the pilot's own stated success metrics (a critical issue, worth a scoped fix even mid-pilot) or is a nice-to-have the customer mentioned in passing (logged, not built, until a pattern across multiple pilots justifies it). This distinction should be made explicitly, not assumed, every time.
