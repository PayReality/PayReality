# Part 4 — Build Roadmap

**Status:** final. **Source:** every task below traces directly to a finding in [03_PRODUCT_GAP_ANALYSIS.md](03_PRODUCT_GAP_ANALYSIS.md)'s ranked list. Complexity is T-shirt sized (S = days, M = one to a few weeks, L = a quarter-ish, XL = multi-quarter/cross-functional with external dependencies) — directional, not a committed estimate.

## Critical

| # | Task | Purpose | Owner | Complexity | Dependencies | Business value |
|---|---|---|---|---|---|---|
| C1 | Move production Postgres off Render's free tier before 2026-08-24 expiry; verify backup/restore actually works post-migration | Prevent a guaranteed, dated production outage | DevOps/SRE | S | None | Existential — a database expiry is not a product-maturity issue, it is a countdown |
| C2 | Wire real alerting/paging (even a lightweight PagerDuty/Opsgenie-equivalent) to the existing `/health`/`/health/ready` checks; schedule the existing `scripts/smoke_test.py` on a cron/uptime service; add basic error tracking (e.g. Sentry) to the backend | Make the platform's "fail closed" promise operationally visible, not just architecturally true | DevOps/SRE | M | C1 | The core enforcement path can silently degrade to universal `HUMAN_REVIEW` with no one aware — this is the highest-leverage operational fix available |
| C3 | Fix or remove the Notifications settings tab's Email/Slack/Teams/webhook controls, which today persist a setting that is never delivered against | Stop presenting a materially misleading control to enterprise evaluators | Backend + Frontend | S (remove/relabel) or M (implement real delivery) | None | Trust — a buyer who discovers this during evaluation will distrust every other claim in the product |
| C4 | Begin a formal SOC 2 Type II readiness program (gap assessment against Trust Services Criteria using `SECURITY.md`/`PRODUCTION_CHECKLIST.md` as the starting baseline) and commission a third-party penetration test | Produce the compliance artifacts this customer base's procurement process will ask for before almost anything else | Founder/Security lead + external auditor | XL | C1, C2 (a stable, monitored production environment is what an auditor actually assesses) | Highest business value in this entire roadmap; also the longest lead time, which is exactly why it must start now, not once every other item is done |
| C5 | Publish a Privacy Policy, Terms of Service, and a baseline Data Processing Agreement template | Close a complete absence of baseline legal artifacts | Founder + legal counsel | M | None | Every enterprise procurement process requires these; cheap relative to the risk of not having them |

## High

| # | Task | Purpose | Owner | Complexity | Dependencies | Business value |
|---|---|---|---|---|---|---|
| H1 | Implement Authorization Receipts v1 per [`RFC_001_AUTHORIZATION_RECEIPTS.md`](../SPECIFICATION/RFC_001_AUTHORIZATION_RECEIPTS.md): schema-versioned receipt issuance alongside today's Evidence record, Merkle-root anchoring, export endpoint | Close the "exportable, independently-verifiable evidence" gap the platform's own roadmap already names as open, against a design that already exists | Backend (Decision Evidence) | L | None technically; benefits from C2's monitoring | The design work is already done — this is the highest-leverage single engineering effort in the whole roadmap because there is no design risk left, only execution |
| H2 | Stand up a staging environment and a minimal CD pipeline (auto-deploy to staging on merge to `main`; deliberate, scripted promotion to production) | Remove "every deploy is a live, unstaged change to production" as the operating norm | DevOps/SRE | M | C1 | Every subsequent change in this roadmap ships more safely once this exists |
| H3 | Replace the founder's-personal-inbox support model with a real, low-cost ticketing tool (Zendesk/Freshdesk/equivalent) and draft a baseline SLA document | Provide a support model that survives a single serious procurement conversation | Founder/Ops | S–M | None | Required before any enterprise contract that includes a support commitment, which every target customer will require |
| H4 | Wire the existing `sdk-python/` test suite (56 tests) into the CI pipeline that already runs the backend suite | Close a real, currently-silent SDK regression risk | Backend/DevOps | S | None | Cheap; prevents the SDK's own advertised test count from becoming another documentation/reality mismatch |
| H5 | Regenerate `docs/openapi.json` and rewrite `docs/API_SPECIFICATION.md` against the live 11 router groups; add a CI check that fails the build if the checked-in spec drifts from the live one | Stop misleading integrators who use the portable reference instead of the live `/docs` | Backend | S | None | Cheap, mechanical, and self-reinforcing once the CI check exists |

## Medium

| # | Task | Purpose | Owner | Complexity | Dependencies | Business value |
|---|---|---|---|---|---|---|
| M1 | Build formatted, scheduled reporting (CSV/PDF export of Decisions/Evidence, optional scheduled email digest) | Serve the target customers' own internal audit/compliance workflows, which run on formatted reports, not raw JSON | Backend + Frontend | L | H1 (reports should reference receipts once they exist); C2/C3 (if emailed) | Directly serves the audit/compliance function inside every target customer organization |
| M2 | Build a provisioning-automation script/runbook for standing up one dedicated PayReality instance per enterprise customer (short of full multi-tenancy) | Let the business onboard several customers without linear, manual ops effort per customer | DevOps/SRE | M | H2 | Scales the business without committing to the much larger multi-tenancy rearchitecture before real demand justifies it |
| M3 | Build a guided, stateful enterprise onboarding wizard (organisation structure -> principals -> first policy -> first agent, carrying state between steps) | Reduce time-to-value for a new customer | Frontend + Backend | L | None | Real value, but lower urgency than Critical/High items given this customer base is typically onboarded white-glove today |
| M4 | Build minimal contract/invoice tracking (an internal tool, not necessarily customer-facing) | Track what each enterprise contract owes and has paid | Founder/Ops | S | None | Operational necessity once there are multiple paying customers; does not require a billing product |

## Low

| # | Task | Purpose | Owner | Complexity | Dependencies | Business value |
|---|---|---|---|---|---|---|
| L1 | Full self-serve multi-tenancy: row-level isolation, an organisation switcher, plural-organisation API endpoints | Support many customers in one shared deployment | Backend (major) | XL | M2 (try provisioning automation first; only build this once real demand outgrows it) | Real long-term value; explicitly not urgent because the target customer base often prefers dedicated instances |
| L2 | Global cross-entity search across agents/decisions/evidence/policies | Usability improvement over today's three independent per-page filters | Frontend + Backend (search index) | M | None | Improves day-to-day usability; not a procurement blocker |
| L3 | BI/analytics dashboards (charts, trends, drill-down) on top of existing Decision/Evidence data | Improve perceived product maturity and stickiness | Frontend | M | None | The underlying data already exists; this is presentation work, not new capability |
| L4 | A second-language SDK (e.g. TypeScript/Node) | Serve a non-Python integration stack | SDK/DevRel | L | None | Only justified once a specific customer integration actually needs it — no such demand is evidenced today |
| L5 | Internationalisation (i18n) infrastructure | Support non-English-speaking users | Frontend | L | None | Not justified today; revisit only if a specific government/enterprise customer in active procurement requires it |
| L6 | Full responsive/mobile layouts for Policy Studio, corpus review, and other data-dense content pages | Support small-viewport use of the full product, not just the nav shell | Frontend | L | None | Explicitly, already correctly deprioritized by the product's own design documentation — this is a desktop-first enterprise console, matching the customer base's own expectations |
