# Part 7 — Implementation Queue

**Status:** final. Every item below is independently executable: a single engineer (or a small, named group) can pick it up, complete it, and ship it without waiting on an item not already listed as its dependency. Nothing here is speculative — each item traces to a specific, evidenced gap in [03_PRODUCT_GAP_ANALYSIS.md](03_PRODUCT_GAP_ANALYSIS.md) and respects the constraints in [05_ARCHITECTURE_CONFORMANCE.md](05_ARCHITECTURE_CONFORMANCE.md). Ticket IDs carry forward the tier codes from [04_BUILD_ROADMAP.md](04_BUILD_ROADMAP.md) so both documents stay cross-referenceable.

## Critical

- **Q-C1.** Provision a paid-tier Render Postgres instance, migrate the production database to it before 2026-08-24, and verify a real backup/restore cycle against the new instance. *Owner: DevOps/SRE. Dependencies: none.*
- **Q-C2a.** Add an error-tracking SDK (e.g. Sentry) to the FastAPI backend at the router/service layer only — never inside `domain/decision/engine.py`. *Owner: Backend. Dependencies: Q-C1.*
- **Q-C2b.** Add a scheduled job (GitHub Actions cron, or a third-party uptime monitor) that runs the existing `scripts/smoke_test.py` against production on a fixed interval and fails loudly on any non-`ALLOW`/expected outcome. *Owner: DevOps/SRE. Dependencies: Q-C1.*
- **Q-C2c.** Wire Q-C2a's error tracker and Q-C2b's scheduled monitor to a real alert channel (at minimum a paged Slack/email webhook; ideally PagerDuty/Opsgenie). *Owner: DevOps/SRE. Dependencies: Q-C2a, Q-C2b.*
- **Q-C3.** Replace the Organization Settings Notifications tab's Email/Slack/Teams/webhook controls — which currently persist settings that are never delivered against — with an honest "Coming soon" state until real delivery (a separate, later item) exists. *Owner: Frontend. Dependencies: none.*
- **Q-C4a.** Run an internal SOC 2 Type II gap assessment against the Trust Services Criteria, using `SECURITY.md`/`PRODUCTION_CHECKLIST.md` as the starting baseline; produce a written list of gaps. *Owner: Founder/Security lead. Dependencies: none.*
- **Q-C4b.** Commission a third-party penetration test against the production API; remediate findings. *Owner: Founder/Security lead + external firm. Dependencies: Q-C1 (test a stable environment).*
- **Q-C5a.** Draft a Privacy Policy and Terms of Service with legal counsel; publish them at `/privacy` and `/terms` frontend routes. *Owner: Founder + legal counsel. Dependencies: none.*
- **Q-C5b.** Draft a baseline Data Processing Agreement template for enterprise contracts. *Owner: Founder + legal counsel. Dependencies: none.*

## High

- **Q-H1a.** Implement Authorization Receipt schema v1 (the 13 fields specified in [RFC-001](../SPECIFICATION/RFC_001_AUTHORIZATION_RECEIPTS.md) §6) as a new record produced alongside every Evidence write, without modifying `decision_engine.py` or `append_evidence`'s existing behavior. *Owner: Backend. Dependencies: none.*
- **Q-H1b.** Implement per-organisation Merkle-root anchoring as a scheduled, asynchronous job, per RFC-001 §5.1 — never a synchronous dependency of `submit_intent`. *Owner: Backend. Dependencies: Q-H1a.*
- **Q-H1c.** Implement a receipt export endpoint and a small, separately-documented, open verification tool (per RFC-001 design goal 1: verifiable without a live API call to PayReality). *Owner: Backend. Dependencies: Q-H1a.*
- **Q-H2a.** Provision a staging Render service and a staging Vercel project, mirroring production configuration. *Owner: DevOps/SRE. Dependencies: Q-C1.*
- **Q-H2b.** Add a CI/CD step that auto-deploys to staging on every merge to `main`. *Owner: DevOps/SRE. Dependencies: Q-H2a.*
- **Q-H2c.** Implement a deliberate, scripted, manually-triggered promotion-to-production step (never automatic). *Owner: DevOps/SRE. Dependencies: Q-H2b.*
- **Q-H3a.** Stand up a lightweight ticketing tool (Zendesk/Freshdesk/equivalent) and route the three existing in-app "Contact" actions to it instead of a personal `mailto:` link. *Owner: Founder/Ops. Dependencies: none.*
- **Q-H3b.** Draft and publish a baseline SLA document. *Owner: Founder/Ops. Dependencies: none.*
- **Q-H4.** Add a `sdk-python` job to `.github/workflows/ci.yml` that installs the SDK and runs its existing pytest suite on every PR. *Owner: Backend/DevOps. Dependencies: none.*
- **Q-H5a.** Regenerate `docs/openapi.json` from the live schema and rewrite `docs/API_SPECIFICATION.md` to cover all 11 live router groups (currently missing auth, users, organization, both AI builders, and runtime policies). *Owner: Backend. Dependencies: none.*
- **Q-H5b.** Add a CI check that fails the build if the checked-in `docs/openapi.json` drifts from the live instance's schema. *Owner: Backend/DevOps. Dependencies: Q-H5a.*

## Medium

- **Q-M1.** Add CSV export for Decisions and Evidence with date-range filtering, as a new endpoint alongside the existing raw-JSON export; PDF formatting as a fast-follow once CSV ships. *Owner: Backend + Frontend. Dependencies: none.*
- **Q-M2.** Write a provisioning runbook/script that stands up one fully independent PayReality instance (database, backend, frontend, OPA) per enterprise customer, cutting today's manual per-customer setup time. *Owner: DevOps/SRE. Dependencies: Q-H2a–c (apply the same staging/CD discipline to the provisioning script itself).*
- **Q-M3.** Build a guided onboarding wizard that sequences organisation-structure setup, principal creation, first-policy authoring, and first-agent registration through the existing service-layer APIs, carrying state between steps. *Owner: Frontend + Backend. Dependencies: none.*
- **Q-M4.** Build a minimal, internal (non-customer-facing) contract/invoice tracking tool, kept entirely outside the Organization/Principal schema Runtime Authority Context resolves from. *Owner: Founder/Ops. Dependencies: none.*

## Low

- **Q-L1.** Design row-level multi-tenancy (schema, service-layer enforcement, organisation switcher) — gated explicitly on a real trigger: attempt Q-M2's provisioning-automation path first, and only decompose this into implementation tickets once a specific customer or scaling event demonstrates dedicated-per-customer instances no longer suffice. *Owner: Backend (major). Dependencies: Q-M2.*
- **Q-L2.** Build a global search endpoint and UI spanning agents, decisions, evidence, and policies, as a read-only index over existing tables. *Owner: Frontend + Backend. Dependencies: none.*
- **Q-L3.** Add a charting library to the frontend and build trend/drill-down views on top of existing Decision/Evidence data for the Assurance page. *Owner: Frontend. Dependencies: none.*
- **Q-L4.** Scope and build a second-language SDK once a specific customer integration requires a non-Python stack. *Owner: SDK/DevRel. Dependencies: a named customer requirement (not yet evidenced).*
- **Q-L5.** Introduce i18n infrastructure once a specific customer requirement for a non-English UI is identified. *Owner: Frontend. Dependencies: a named customer requirement (not yet evidenced).*
- **Q-L6.** Build full responsive layouts for Policy Studio, corpus review, and other data-dense pages, if and when mobile/tablet use of these specific screens is actually requested. *Owner: Frontend. Dependencies: a named customer requirement (not yet evidenced).*
