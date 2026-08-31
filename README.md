# PayReality

**Enterprise AI Authority Infrastructure.**

PayReality gives an AI agent a real identity, a real delegated authority limit, and a real deterministic gate in front of every consequential action it tries to take. Every decision, allow, deny, or escalate to a human, produces a cryptographically signed Evidence record it cannot quietly rewrite later, bound permanently to the exact policy version that governed it.

**Authority Graph**: governance documents (SOPs, delegation-of-authority matrices, approval policies), extracted with provenance and reviewed by a human before anything becomes enforceable.
**Runtime Policies**: the compiled, versioned Rego bundle that authority becomes, one per organization.
**Runtime Authority**: every Intent an agent submits, evaluated deterministically against the active Runtime Policy before anything executes. Zero LLM sits on this path.
**Evidence**: an ED25519-signed, hash-chained record of what was decided and why, for every Decision and every resolution, independently verifiable and unaffected by later policy changes.
**Assurance**: a live read of what's actually running, including agent count, active policies, and decision volume by outcome.

This is not a demo of what that would look like. `server/` is a working FastAPI + PostgreSQL + Open Policy Agent backend, running live in production on Azure; the frontend and Python SDK call it for real, with no mocked data and no scripted outcomes. See [PRODUCT.md](PRODUCT.md) for what that means in practice, and [ARCHITECTURE.md](ARCHITECTURE.md) for how it's built.

---

## How a decision actually happens

1. An **Agent** (a certificate-holding identity acting for a Principal) submits an **Intent**, signed with its private key, which never leaves wherever it was generated, via the API or the Python SDK's `authorize()` call.
2. **Runtime Authority** builds an OPA input document and queries that organization's active **Runtime Policy bundle** (compiled Rego, built from human-approved authority, one bundle per organization).
3. OPA returns `allow`, `deny`, or nothing decisive. Anything not explicitly `allow` resolves to `HUMAN_REVIEW`. This is fail-closed by construction: an OPA timeout, an OPA error, an unrecognized action, or no active policy all also resolve to `HUMAN_REVIEW`, never `ALLOW`.
4. An **Evidence** record is signed (ED25519, over a SHA-256 digest of the canonical JSON payload) and stored in the same transaction as the decision, hash-chained to the previous record. A `HUMAN_REVIEW` decision that's later approved or denied appends a *second* Evidence record rather than mutating the first; the Decision row itself never changes after it's written, and stays bound to the exact policy version that produced it, permanently, even after that policy is later changed.
5. **Assurance** reads real counts and real recent Decisions from the same database, scoped to the caller's own organization. It is not a static or seeded view.

## Repository layout

```
server/                FastAPI backend: decision engine, OPA client, policy compiler,
                        evidence signing, RBAC, multi-tenant isolation, Alembic migrations
server/tests/           367 unit tests, 69 integration tests (real OPA, real Postgres-shaped fixtures)
sdk-python/             The official Python SDK (payreality package): register/authorize/heartbeat/
                        retire, ED25519 signing handled for you; see sdk-python/README.md
src/app/                React + Vite frontend: Overview, Agents, Governance (Authority Builder,
                        Policy Studio), Decisions, Evidence, Assurance, Organisation Settings
AZURE_MIGRATION/        Terraform for the live Azure infrastructure (prod + staging); see its own
                        README.md for the required init-env.sh workflow before any plan/apply
.github/workflows/      Real CI (tests) and CD (build + deploy on every push to main) for both
                        the backend and the frontend
docker-compose.yml      Postgres + OPA + the API, wired the way a real deploy is wired
render.yaml             Historical record only. Render has been fully retired (backup verified,
                        restore-tested, and decommissioned); Azure is the sole production host.
scripts/                scripts/smoke_test.py: end-to-end pipeline check against any live instance
openapi.json            Exported OpenAPI schema for every live endpoint
SPECIFICATION/          The platform's own 49-part internal architecture handbook, including a
                        dedicated current-limitations part and a candid architectural assessment
BACKLOG_V1_CLOSURE.md   The current, live-verified backlog: what's actually still open right now
GAVIN_ABSA_PRODUCT_AUDIT.md / GAVIN_REMEDIATION_PLAN.md
                        The active initiative: closing the gap between a real enterprise sales
                        briefing and what the product does today, tracked in issue #3 and its
                        nine child issues
```

## Running it locally

Backend (needs Docker, or a local Postgres + `opa` binary):

```
docker compose up --build
```

or without Docker, see `server/.env.example` for the required environment variables and `server/pyproject.toml` for dependencies (`pip install -e ".[dev]"`, then `alembic upgrade head`, then `uvicorn app.main:app --reload`).

Frontend:

```
npm install
npm run dev
```

Set `VITE_API_URL` (see `.env.example`) to point at the backend above.

## Documentation

**Current and active:**

* [BACKLOG_V1_CLOSURE.md](BACKLOG_V1_CLOSURE.md): the real, live-verified backlog. Start here for what's actually still open right now, not a historical snapshot.
* [GAVIN_ABSA_PRODUCT_AUDIT.md](GAVIN_ABSA_PRODUCT_AUDIT.md) / [GAVIN_REMEDIATION_PLAN.md](GAVIN_REMEDIATION_PLAN.md): the active initiative, closing the gap between a real enterprise sales briefing and what the product does today. Tracked in issue #3 and its nine child issues.
* [ENTERPRISE_MESSAGING_GUIDE.md](ENTERPRISE_MESSAGING_GUIDE.md): the single source of truth for how PayReality should be described, anywhere — website, sales, pilot material. [WEBSITE_CLAIMS.md](WEBSITE_CLAIMS.md) is its compact extract for the next website milestone; [DEMO_NARRATIVE.md](DEMO_NARRATIVE.md) is the equivalent for the next demo milestone.
* [TRUSTED_ADAPTER_GUIDE.md](TRUSTED_ADAPTER_GUIDE.md): plain-English explainer for the Trusted Integration Architecture's customer-deployed Adapter component — what it is, where it runs, what it does and doesn't prove.
* [AUDITOR_ASSURANCE_GUIDE.md](AUDITOR_ASSURANCE_GUIDE.md): a short Q&A for independently verifying what PayReality's Evidence/Receipt records do and don't show.
* [sdk-python/README.md](sdk-python/README.md), [SDK_ARCHITECTURE.md](SDK_ARCHITECTURE.md), [SDK_REFERENCE.md](SDK_REFERENCE.md), [SDK_SECURITY.md](SDK_SECURITY.md): the Python SDK, covering both the agent-direct and Trusted Adapter runtime paths.
* [AZURE_MIGRATION/terraform/README.md](AZURE_MIGRATION/terraform/README.md): required reading before touching Terraform here (prod/staging state separation).
* [docs/API_SPECIFICATION.md](docs/API_SPECIFICATION.md): every real endpoint, its auth requirement, and its schema (`openapi.json` is the machine-readable source).
* [SECURITY.md](SECURITY.md): superseded by [SPECIFICATION/14_SECURITY_MODEL.md](SPECIFICATION/14_SECURITY_MODEL.md); kept as a design-time record.

**Architecture and design history** (some of these predate multi-tenancy, RBAC, and the AI Authority Builder shipping; treat as historical design record for how the current system got here, not as a live status report):

* [PRODUCT.md](PRODUCT.md): what PayReality is, is not, and how a customer derives value from it
* [ARCHITECTURE.md](ARCHITECTURE.md): system design, data flow, and the decision/evidence pipeline in detail
* [DOMAIN_ABSTRACTION.md](DOMAIN_ABSTRACTION.md): which parts of the engine are domain-agnostic versus financial-specific
* [AUTHORING_ARCHITECTURE.md](AUTHORING_ARCHITECTURE.md): the canonical Runtime Policy model and the authoring modes that produce it -- the AI Authority Builder mode described here as design-only is now real and shipped
* [RUNTIME_POLICY_LANGUAGE.md](RUNTIME_POLICY_LANGUAGE.md): the `RuntimePolicy` domain model (`server/app/domain/runtime_policy/`) -- now the live, active policy model, not merely isolated
* [POLICY_LANGUAGE_SPEC.md](POLICY_LANGUAGE_SPEC.md): the small condition language Policy Studio's manual authoring mode uses instead of exposing Rego
* [POLICY_COMPILER_V2.md](POLICY_COMPILER_V2.md) / [COMPILER_V2_ARCHITECTURE.md](COMPILER_V2_ARCHITECTURE.md): Compiler V2 (`server/app/domain/compiler_v2/`) -- now the sole compiler, enforcing every condition including field-vocabulary validation, verified against a real OPA server
* [POLICY_STUDIO.md](POLICY_STUDIO.md): the manual policy-authoring editor's design, Monaco integration, validation, and versioning
* [DEPLOYMENT.md](DEPLOYMENT.md), [GO_LIVE.md](GO_LIVE.md), [OPERATIONS_RUNBOOK.md](OPERATIONS_RUNBOOK.md), [PRODUCTION_CHECKLIST.md](PRODUCTION_CHECKLIST.md): the original path to production -- superseded in practice by the real Azure cutover and the CD pipeline in `.github/workflows/`, kept for historical record
* [VERSION_3_ROADMAP.md](VERSION_3_ROADMAP.md), [DOMAIN_REFACTOR_PLAN.md](DOMAIN_REFACTOR_PLAN.md): earlier forward-looking plans; check BACKLOG_V1_CLOSURE.md first for what's actually current
* [SPECIFICATION/](SPECIFICATION/): the platform's own 50-part internal architecture handbook, including a dedicated current-limitations part, a candid architectural assessment, and (Part 50) the Trusted Integration Architecture

## Status

**Live in production**, on Azure, at `api.aisecurewatch.com` (backend) and `payreality.aisecurewatch.com` (dashboard). Render was retired after a live, data-verified restore drill; Azure is the only production host. Both frontend and backend deploy automatically on every push to `main` via `.github/workflows/`.

Real RBAC exists: six roles (Owner, Governance Admin, Agent Admin, Reviewer, Auditor, Executive), permission-gated on every route, verified in real authenticated sessions, not just source inspection. The Operator Key is platform-admin-only and requires an explicit target organization on every call, not an implicit default. Multi-tenant isolation is real: one OPA package and one policy set per organization, with dedicated regression tests.

Runtime Authority, Compiler V2, Evidence signing and chain verification, key rotation, and historical policy binding (a decision stays correctly explainable against the exact policy version that governed it, forever, even after later changes) are all real and covered by passing tests: 367 backend unit tests, 69 integration tests against a real OPA server, 72 SDK tests.

The current, accurate list of what's still genuinely open is [BACKLOG_V1_CLOSURE.md](BACKLOG_V1_CLOSURE.md), not this section. The active initiative is closing the gap between the real product and a sales briefing already sent to a real enterprise prospect -- see [GAVIN_ABSA_PRODUCT_AUDIT.md](GAVIN_ABSA_PRODUCT_AUDIT.md) and issue #3.

## License

Proprietary. All Rights Reserved.
