# Azure Migration Program — Milestone 5: Go/No-Go Production Cutover Report

## Recommendation

# READY FOR PRODUCTION CUTOVER

**for the core platform** — with two named, non-blocking residual items and one explicit feature-level gap disclosed below, none of which represent unknown risk to the platform's correctness, security, or availability. This report is a recommendation only: per every prior milestone's rules, no DNS change, customer traffic migration, or actual cutover has been performed or is proposed here.

## Why this is different from Milestone 4's "NOT READY"

Milestone 4 named four specific, concrete blockers. Every one has now been closed with live evidence, not just configuration:

| Milestone 4 blocker | Milestone 5 resolution | Evidence |
|---|---|---|
| No alert rules — nothing pages on failure | Five real metric alert rules deployed, notification path tested live | `az monitor action-group test-notifications` → real email sent, `Status: Succeeded` |
| Application Insights received zero telemetry | Fully instrumented, opt-in, zero impact on Render | Live query: real `requests`/`dependencies`/`traces` rows |
| PITR restore never rehearsed | A full restore drill was performed and its data verified | Restored server's Alembic revision, org count, and signing-key count matched the source exactly |
| Evidence signing key was a placeholder | Real Ed25519 key generated, installed, and cryptographically validated | API's own public-key endpoint matches an independently-computed value byte-for-byte |

Milestone 5 also added two things Milestone 4 didn't require but this milestone's own success criteria did: a monitoring dashboard (deployed, zero drift) and a **live-tested** rollback plan (not just a written procedure — an actual bad deployment was performed and rolled back, revealing a genuinely valuable finding: Container Apps' `Single` revision mode did not drop traffic during the failed deploy, because ingress kept routing to the last healthy revision despite the broken one nominally holding 100% traffic weight).

## The two non-blocking residual items

1. **Alert rule live-fire test coverage is partial.** All five rules are confirmed correctly configured against real, valid metrics, and the notification *delivery* mechanism is proven working end-to-end. What wasn't achieved: an organic metric breach for two of the five rules within this milestone's testing window (`RestartCount` doesn't respond to a CLI-initiated restart — it tracks platform-detected crashes specifically; the CPU-high threshold couldn't be forced against the lightweight `/health` endpoint even under sustained load). This is a gap in test *coverage*, not in configuration — recommend closing it opportunistically the next time a real restart or load event occurs naturally, rather than engineering an artificial one.
2. **The PITR restore-test server is a new, real, ongoing-cost resource** (`psql-payreality-staging-cus-restoretest`, ~$14/month) that this program's own rules don't authorize deleting without explicit approval. **Decision needed:** keep it (as a standing, already-verified DR artifact) or approve its deletion.

## The one disclosed feature-level gap

`ANTHROPIC_API_KEY` remains Milestone 2's placeholder value. This is a third-party credential this program cannot generate on its own — it requires the actual Anthropic account credential. It does not block platform readiness (the core authorization/evidence/audit path has no dependency on it), but AI-assisted features (Policy Builder, Authority Builder document ingestion) will not function until it's set, the same way the Evidence signing key didn't block the platform but did block signature-dependent functionality until this milestone closed it.

## What "ready" means here, precisely

The Azure staging environment:
- Runs the real application, byte-identical in API surface to Render (Milestone 4).
- Signs Evidence with a real, validated cryptographic key.
- Authenticates administrative actions with a real credential, not a placeholder string.
- Emits real, queryable application-level telemetry in addition to the platform-level logs Milestone 3/4 already confirmed.
- Pages a real notification target when its most consequential failure modes occur.
- Has a demonstrated, working backup-restore capability, not just a configured one.
- Has a rollback procedure that has actually been exercised once, successfully, under a real (if deliberately induced) failure.
- Shows zero Terraform drift and 194/194 passing tests after every change made this milestone.

## What this report does not authorize

DNS changes, customer traffic migration, database migration, or any production cutover action. Those remain explicitly out of scope for every milestone in this program to date, including this one. The next action, if this recommendation is accepted, is a separate, explicitly-scoped cutover milestone — not an automatic continuation from this report.
