# Part 3 — Product Gap Analysis

**Status:** final. **Method:** the architecture is deliberately ignored in this document, per the directive. Every finding below is grounded in direct inspection of `src/app/` (frontend), `sdk-python/`, `docs/`, `.github/workflows/`, and the root-level operational documents (`DEPLOYMENT.md`, `GO_LIVE.md`, `PRODUCTION_CHECKLIST.md`, `OPERATIONS_RUNBOOK.md`, `SECURITY.md`), gathered via two dedicated audits this phase. This document asks one question per category: **what does a world-class commercial platform serving insurers, banks, governments, and Fortune 500 companies need here that PayReality does not yet have?**

## Customer experience

**Exists:** a documented, semi-mature design system (`--pr-*` design tokens, shared `ui/` primitives, a completed WCAG-AA-targeted accessibility remediation pass — focus states, labels, `aria-live` regions, skip-to-content link). A working mobile-aware navigation shell.
**Missing:** no global, cross-entity search (three independent per-page filters only); no i18n (zero locale infrastructure, all copy hardcoded English); content pages (Policy Studio's forms, the Authority corpus review, data tables) have no responsive layout below tablet width, by the product's own documented admission; the accessibility pass explicitly disclaims full WCAG AA certification (no screen-reader manual testing, no colour-blind-safe palette validation).

## Enterprise onboarding

**Exists:** a first-run Owner-claim flow (`/setup-owner`) and an optional, skippable "Getting Started" checklist (six linked steps, completion tracked in `localStorage`).
**Missing:** no guided, stateful onboarding wizard — a new customer's organisation, principals, first policy, and first agent are set up via three separate, disconnected top-level nav destinations with no forced sequence and no carried state between steps. There is no self-service organisation creation at all: an organisation is provisioned before a customer ever logs in, consistent with today's single-tenant-per-deployment model.

## Dashboards

**Exists:** an Overview page and an Assurance page, both real, both live-computed from the actual database.
**Missing:** both are explicitly *not* dashboards in the analytics sense — the Overview page's own heading states "One workflow, not a dashboard," showing two numbers and a linked task list; Assurance shows five static stat cards with no trend-over-time, no drill-down, no date-range filter, and no chart of any kind. Zero charting library exists in the frontend's dependency tree.

## Approvals

**Exists and is functional:** a permission-gated Review Queue page for resolving `HUMAN_REVIEW` decisions, backed by a real API (`resolution_service.resolve_decision`). This is one of the product's more complete surfaces — no material gap found here.

## Policy management

**Exists and is comparatively mature:** three independent authoring paths (manual Policy Studio, single-document AI Policy Builder, multi-document AI Authority Builder), version history, a merged compile/dry-run/deploy publish flow. **Known, already-documented gaps** (not rediscovered here, carried from [32](../SPECIFICATION/32_PHASE_3_GAP_ANALYSIS.md)/[40](../SPECIFICATION/40_PHASE_4_GAP_ANALYSIS.md)): no currency vocabulary or condition support; Compiler V2 validates only the `action` field, not `resource`/other fields.

## Runtime monitoring

**Exists:** a health-check tab (Organisation Health: engine, evidence, OPA, compiler, database, Anthropic connectivity) and a synthetic end-to-end smoke-test script.
**Missing — this is a severe gap given the product's own "fail closed" promise:** the smoke test is run manually, not scheduled; there is no APM or error-tracking integration anywhere (confirmed by repo-wide search — zero Sentry/Datadog/OpenTelemetry/Prometheus), no metrics or tracing, no real alerting/paging (`PRODUCTION_CHECKLIST.md` explicitly marks this "not wired yet"), and no external status page. **A silent OPA or database outage today produces no page to anyone** — it degrades every Decision to `HUMAN_REVIEW` (fail-closed, architecturally correct) but nothing tells a human that is happening until someone notices a backlog.

## Investigation workflows

**Exists:** an Agent Detail page that surfaces an agent's decision history and evidence; direct links between related entities where the UI happens to place them.
**Missing:** no dedicated case/investigation tool for "here is a suspicious pattern, walk me through everything related to it" — no saved queries, no annotation, no cross-entity timeline view. The "Audit Trail" as a distinct concept is, by the product's own code comment, the same underlying Evidence ledger as everything else, not a separate investigative surface.

## Reporting

**Missing entirely** beyond one raw export: the only export capability anywhere is a client-side "download the full Evidence array as JSON" button. No CSV/PDF, no formatted or paginated report, no scheduling, no template. For a customer base whose own compliance and audit functions run on formatted reports, not raw JSON blobs, this is a real gap.

## Evidence browsing

**Exists and is functional:** an Evidence page with per-record signature verification. **Missing:** the portable, independently-verifiable "Authorization Receipt" format already fully designed in [`SPECIFICATION/RFC_001_AUTHORIZATION_RECEIPTS.md`](../SPECIFICATION/RFC_001_AUTHORIZATION_RECEIPTS.md) — a 13-field receipt spec (schema-versioned, hash-chained, Merkle-anchored, minimal-disclosure by design) that directly answers the exact "exportable, independently-verifiable evidence bundle" gap `VERSION_3_ROADMAP.md` names as still open. This is the single clearest instance in this whole audit of a fully-designed, unimplemented capability — not a gap needing new design work, a gap needing engineering execution against an existing spec.

## Administration

**Exists and is comparatively mature:** a ten-tab Organization Settings surface (structure, security/API keys, integrations, enterprise systems, notifications, audit, health, about) and RBAC user management across six fixed roles. **One concrete, user-facing defect found in this audit:** the Notifications tab's Email/Slack/Teams/webhook controls persist settings that are never actually delivered against — the component itself renders a disclaimer admitting this to the user. That is a materially misleading control for an enterprise buyer evaluating the product, not merely an incomplete feature.

## Multi-tenancy

**Confirmed absent at every layer**, consistently across schema, API, and UI: `organization_id` columns exist but enforce nothing at the row level (`SECURITY.md`'s own admission); there is no plural "organizations" API endpoint anywhere; there is no organisation switcher in the UI; the session model assumes exactly one organisation per user. Today's model is one full deployment per customer. **Nuance for the target customer base**: banks, insurers, and governments frequently *prefer* single-tenant, dedicated-instance deployments for isolation guarantees — so this gap is less severe for initial enterprise sales than it would be for a self-serve SaaS, but it is a severe gap for *operational scalability* the moment more than a handful of customers exist, since each is a hand-provisioned deployment today.

## Billing

**Confirmed completely absent**, frontend and backend: no Stripe or any payment integration, no subscription/invoice/plan model, no usage-based metering, no per-plan rate limiting (today's rate limiter is a single flat, plan-agnostic, in-process limiter). **Nuance**: this customer base is procured and invoiced, not self-served with a credit card — so a full self-serve billing system is not the actual near-term need; a much smaller capability (the ability to track and invoice a handful of enterprise contracts) is.

## Audit

**Exists:** hash-chained, ED25519-signed Evidence with per-organisation chain scope, a `/verify` endpoint, and an export button. **Missing, and this is the single largest gap found in this entire audit for the stated customer base:** zero compliance artifacts of any kind. Repo-wide search found no SOC 2 report or in-progress program, no ISO 27001 documentation, no GDPR artifacts (no privacy policy, no terms of service, no data-processing-agreement template — and no corresponding frontend routes), no HIPAA documentation, no completed penetration test, and no security-questionnaire response template. `SECURITY.md` and `PRODUCTION_CHECKLIST.md` are genuinely good internal engineering self-assessments, and `VERSION_3_ROADMAP.md` itself already correctly names SOC 2 as future, Series-A-stage work — but a bank, insurer, or government's procurement process will ask for artifacts that do not exist today, before it asks almost anything else in this report.

## APIs

**Exists:** a live, accurate, auto-generated OpenAPI/Swagger surface at `/docs`/`/openapi.json` on the running instance — this cannot drift, by construction. **Missing:** both hand-maintained, portable references (`docs/openapi.json`, checked into the repo, and `docs/API_SPECIFICATION.md`) are stale — missing 6 of the 11 live router groups entirely (auth, users, organization, both AI builders, runtime policies), and `docs/API_SPECIFICATION.md` actively states human login/RBAC doesn't exist, when it has for several phases. An integrator relying on the checked-in reference rather than the live instance would be actively misled.

## SDKs

**Exists:** a real, packaged, installable Python SDK (`sdk-python/`, version `0.1.0`, real `pyproject.toml`, ED25519 signing built in, 56 tests, usage examples). **Missing:** no SDK for any other language (confirmed by full-repo search — no JS/TS/Java/Go SDK exists anywhere); no changelog or semantic-versioning policy for the one SDK that exists; and — a genuine, previously-undocumented finding from this audit — **the SDK's own test suite is not wired into CI at all**, so its advertised "56 passing tests" is not continuously verified and could silently regress.

## Documentation

**Exists:** an unusually thorough internal architecture reference (`SPECIFICATION/`, 52 files) and an in-app Help drawer (Getting Started, Learn glossary, Troubleshooting, Developer resources, Contact). **Missing:** a genuine external developer portal distinct from the internal specification set; the customer/developer-facing API reference is stale (see APIs, above); no versioned public changelog for the platform or the SDK.

## Deployment

**Exists:** a real, live production deployment (Render backend behind a custom domain with a valid TLS certificate, Vercel frontend), a CI pipeline that runs the full backend test suite plus a Docker build plus a frontend build on every PR. **Missing, and one item here is genuinely urgent and dated:** the production Postgres database is on Render's **free tier, documented as expiring 2026-08-24** — roughly two weeks from this audit; there is no staging environment anywhere; there is no continuous-deployment pipeline (deploys are manual, imperative calls against Render's REST API); and there is no general-purpose infrastructure-as-code (the one `render.yaml` Blueprint file exists but was never actually applied — the real environment was provisioned imperatively).

## Operations

**Exists:** structured JSON request logging, liveness/readiness health endpoints, a documented (if never-drilled) disaster-recovery procedure, and a genuinely good internal incident-response runbook.
**Missing:** everything under Runtime Monitoring, above, applies equally here — no APM, no scheduled synthetic monitoring, no paging, no external status page. The disaster-recovery restore procedure has never actually been exercised against this schema.

## Support

**Exists:** an in-app Help drawer and three contact actions.
**Missing:** every contact action resolves to a `mailto:` link to the founder's personal email address — there is no ticketing system, no SLA document of any kind, and no customer-facing incident-communication process (the internal runbook is engineering-only). For the stated customer base, "email the founder" is not a support model that will survive a single serious procurement conversation.

## Ranked list of missing capabilities (business importance, highest first)

1. **Compliance artifacts (SOC 2 path, pentest, security questionnaire response, DPA/privacy policy/terms)** — Audit/Compliance. Blocks initial procurement with the stated customer base more than any other single gap; today there is nothing to hand a vendor-risk team beyond internal engineering docs.
2. **Production database expiring 2026-08-24 (free-tier Postgres)** — Deployment. Time-boxed, concrete, and catastrophic if missed — a production outage from database expiry is unrelated to product maturity and entirely avoidable.
3. **Real alerting/paging + APM/error tracking + scheduled synthetic monitoring** — Operations/Runtime Monitoring. The platform's core promise is "fail closed," which is architecturally sound but operationally silent — nobody is paged when the fail-closed path is the one actually firing in production.
4. **Notification-settings UI that doesn't actually deliver anything** — Administration. A materially misleading control shown to enterprise buyers; either wire it up or remove it.
5. **Portable, independently-verifiable evidence export (RFC-001 execution)** — Evidence Browsing/Audit. Already fully designed; the highest-leverage single engineering effort in this list because the design work is already done.
6. **Staging environment + CD pipeline** — Deployment/Operations. Every deploy today is a manual, unstaged production change.
7. **Support model beyond a founder's personal inbox (ticketing + SLA)** — Support. Required before any enterprise contract that includes a support commitment, which every customer in the stated base will require.
8. **SDK test suite wired into CI** — SDKs. Cheap, mechanical, and closes a real, currently-silent regression risk.
9. **Formatted/scheduled reporting (beyond raw JSON export)** — Reporting. Matters for the compliance and audit functions the target customers actually run internally.
10. **Multi-tenancy or, short of that, provisioning automation for one-deployment-per-customer** — Multi-tenancy. Less urgent for initial sales (dedicated instances are often preferred by this customer base) but blocks scaling past a handful of customers without heavy manual ops.
11. **Stale API reference docs (`docs/openapi.json`, `docs/API_SPECIFICATION.md`)** — APIs/Documentation. Actively misleading, cheap to fix (regenerate + rewrite), lower stakes than the items above because the live `/docs` is accurate.
12. **Guided enterprise onboarding flow** — Enterprise Onboarding. Matters for time-to-value; likely less urgent than the above because this customer base is typically onboarded white-glove, not self-serve.
13. **BI/analytics dashboards (charts, trends)** — Dashboards. A real gap but not a procurement blocker; the underlying data already exists for this to be built later without any architecture change.
14. **Billing/invoicing capability** — Billing. Full self-serve billing is not needed for this customer base; a minimal contract/invoice-tracking capability is a smaller, later need.
15. **Global cross-entity search** — Customer Experience. A usability improvement, not a blocker.
16. **A second-language SDK** — SDKs. Only justified once a real customer integration demands a non-Python stack; no evidence of that demand exists today.
17. **i18n** — Customer Experience. Not justified today; revisit if a specific non-English-speaking government customer is in active procurement.
18. **Full responsive/mobile layouts for content pages** — Customer Experience. Explicitly, correctly deprioritized already by the product's own design documentation; this is an internal enterprise console, not a consumer app.
