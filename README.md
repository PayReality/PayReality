# PayReality

**Runtime Trust Infrastructure for Autonomous AI Agents.**

PayReality gives an AI agent a real identity, a real delegated authority limit, and a real deterministic gate in front of every financial action it tries to take. Every decision, allow, deny, or escalate to a human, produces a cryptographically signed Evidence record it cannot quietly rewrite later.

**Authority**: an agent's certificate and the Mandates it acts under.
**Policy**: the compiled, versioned Rego bundle those Mandates become.
**Runtime Decisions**: every Intent an agent submits, evaluated against the active Policy before anything executes.
**Evidence**: an ED25519-signed record of what was decided and why, for every Decision and every resolution.
**Assurance**: a live read of what's actually running, including agent count, active Policy, and Decision volume by outcome.

This is not a demo of what that would look like. `server/` is a working FastAPI + PostgreSQL + Open Policy Agent backend; the frontend calls it for real, with no mocked data and no scripted outcomes. See [PRODUCT.md](PRODUCT.md) for what that means in practice, and [ARCHITECTURE.md](ARCHITECTURE.md) for how it's built.

---

## How a decision actually happens

1. An **Agent** (a certificate-holding identity acting for a Principal) submits an **Intent**, signed with its private key, which never leaves wherever it was generated.
2. The **Decision Engine** builds an OPA input document and queries the active **Policy** (a compiled Rego bundle built from human-approved **Authorities**).
3. OPA returns `allow`, `deny`, or nothing decisive. Anything not explicitly `allow` resolves to `HUMAN_REVIEW`. This is fail-closed by construction: an OPA timeout, an OPA error, or no active Policy all also resolve to `HUMAN_REVIEW`, never `ALLOW`.
4. An **Evidence** record is signed (ED25519, over a SHA-256 digest of the canonical JSON payload) and stored. A `HUMAN_REVIEW` decision that's later approved or denied appends a *second* Evidence record rather than mutating the first; the Decision row itself never changes after it's written.
5. **Assurance** reads real counts and real recent Decisions from the same database. It is not a static or seeded view.

## Repository layout

```
server/            FastAPI backend: decision engine, OPA client, policy compiler,
                    evidence signing, Alembic migrations
server/tests/      36 unit tests covering the decision engine, compiler, and signing
src/app/           React + Vite frontend, one workflow-ordered nav:
                   Overview -> Authority -> Policy -> Runtime Decisions -> Evidence -> Assurance
docker-compose.yml Postgres + OPA + the API, wired the way a real deploy is wired
render.yaml         Render Blueprint: today's live production host. Azure is the verified
                    target platform, not yet cut over; see MILESTONE_4_AZURE_PRODUCTION_READINESS_SUMMARY.md
scripts/            scripts/smoke_test.py: end-to-end pipeline check against any live instance
openapi.json        Exported OpenAPI schema for every live endpoint
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

* [PRODUCT.md](PRODUCT.md): what PayReality is, is not, and how a customer derives value from it
* [ARCHITECTURE.md](ARCHITECTURE.md): system design, data flow, and the decision/evidence pipeline in detail
* [DOMAIN_ABSTRACTION.md](DOMAIN_ABSTRACTION.md): which parts of the engine are already domain-agnostic versus financial-specific, and the target adapter model for future domains without touching Financial Services as the GTM focus
* [DOMAIN_REFACTOR_PLAN.md](DOMAIN_REFACTOR_PLAN.md): the itemized, sequenced plan for that abstraction, with risk and priority per item, not yet executed
* [AUTHORING_ARCHITECTURE.md](AUTHORING_ARCHITECTURE.md): the canonical Runtime Policy model, and how the three authoring modes (guided wizard, manual, AI builder) all produce it; design only, not yet built
* [RUNTIME_POLICY_LANGUAGE.md](RUNTIME_POLICY_LANGUAGE.md): the `RuntimePolicy` domain model itself (`server/app/domain/runtime_policy/`), built and tested, fully isolated, not wired into anything yet
* [POLICY_LANGUAGE_SPEC.md](POLICY_LANGUAGE_SPEC.md): the small condition language Policy Studio's manual authoring mode uses instead of exposing Rego
* [POLICY_COMPILER_V2.md](POLICY_COMPILER_V2.md): what compiling an arbitrary Runtime Policy into Rego actually requires, including the honest finding that today's compiler doesn't enforce most conditions at all
* [COMPILER_V2_ARCHITECTURE.md](COMPILER_V2_ARCHITECTURE.md): Compiler V2 itself (`server/app/domain/compiler_v2/`), built and verified against a real OPA server, including proof that the unmodified Decision Engine can consume its output
* [POLICY_STUDIO.md](POLICY_STUDIO.md): the manual policy-authoring editor's design, Monaco integration, validation, and versioning
* [docs/API_SPECIFICATION.md](docs/API_SPECIFICATION.md): every real endpoint, its auth requirement, and its schema (`openapi.json` is the machine-readable source)
* [DEPLOYMENT.md](DEPLOYMENT.md): hosting recommendation, environment variables, CI/CD, rollback, monitoring
* [GO_LIVE.md](GO_LIVE.md): the literal step-by-step procedure to take the backend from packaged to actually live
* [OPERATIONS_RUNBOOK.md](OPERATIONS_RUNBOOK.md): day-2 operations once it's live, monitoring, incident response, rollback
* [PRODUCTION_CHECKLIST.md](PRODUCTION_CHECKLIST.md): every production-readiness requirement, checked off only where actually true
* [SECURITY.md](SECURITY.md): full security posture, including what's covered, what's a known gap, and why
* [VERSION_3_ROADMAP.md](VERSION_3_ROADMAP.md): what's next, phased by how far along the company is, not by feature wishlist

## Status

The Runtime Authority engine, policy pipeline, and Evidence signing are real and covered by passing tests. The backend is not yet hosted anywhere reachable by the live frontend. See GO_LIVE.md for the recommended path and SECURITY.md / ARCHITECTURE.md for exactly what "real" does and doesn't cover today. There is no human login/RBAC system yet; a single shared operator credential gates the endpoints that would otherwise need one (see SECURITY.md).

## License

Proprietary. All Rights Reserved.
