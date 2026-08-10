# Sprint 1, Part 2 — Production Infrastructure Blueprint

**Status:** final. **Principle:** stay on Render + Vercel. Both already work, both are already live, and neither has hit a real limit yet — moving to a new cloud provider, a container orchestrator, or a new managed-database vendor would be exactly the kind of unnecessary service this sprint's own instruction says to avoid. Everything below is the smallest change that closes [01_INFRASTRUCTURE_ASSESSMENT.md](01_INFRASTRUCTURE_ASSESSMENT.md)'s identified risks.

## The four environments

**Local and Development are the same mechanism, used two ways — stated honestly rather than inventing a fifth thing to seem more thorough.** `docker-compose.yml` (Postgres + embedded-topology OPA + the API) is what an individual engineer runs on their own machine (**Local**). The identical mechanism, shared, is what a **Development** check happens to be for this team's size: a Vercel Preview Deployment (automatic per-PR today, no new setup) for the frontend, and — until real demand for a persistent shared backend dev environment appears — the same `docker-compose.yml` run against a disposable, seedable local database for backend work. No new persistent cloud "development" tier is provisioned; one would sit idle most of the time for a team this size and is exactly the unnecessary service this blueprint avoids.

**Staging** is the one genuinely new, persistent environment this blueprint adds: a second Render web service and a second (small, cheap) Render Postgres instance, mirroring production's topology exactly (embedded OPA, same Docker image, same environment-variable shape). A second Vercel project, same build, pointed at the staging API.

**Production** is today's existing Render web service and Postgres instance, upgraded per the changes below — not replaced, not moved.

## Cloud services

| Concern | Choice | Why |
|---|---|---|
| Compute (API + embedded OPA) | Render Web Service, Docker runtime — unchanged | Already live, already working, zero migration risk |
| Frontend | Vercel — unchanged | Same |
| Database | Render managed Postgres — unchanged provider, upgraded plan (below) | Render's own backup/PITR feature only exists on paid plans; upgrading is the entire fix, no new vendor needed |
| Object storage | **None added.** Documents stay in Postgres. | See [01](01_INFRASTRUCTURE_ASSESSMENT.md)'s storage finding — at today's volume this is a real but tolerable simplification; revisit only if the primary database's size or backup time actually becomes a problem, not preemptively |
| DNS | Existing domain/registrar, unchanged | Add one new subdomain for staging; no new provider |
| Secrets | Render/Vercel's own environment-variable stores, upgraded process (see [04](04_SECRETS_MANAGEMENT_GUIDE.md)) | A dedicated secrets manager (AWS Secrets Manager, Vault) is explicitly **not** recommended yet — see that document for the threshold at which it would be |

## Database strategy

One primary Postgres instance per environment (staging, production), each single-node — no read replica, no connection pooler. At today's traffic volume neither is justified; both are cheap to add later behind the same connection string if query load ever actually demands it. Production moves from Render's free tier to a **paid plan with automated backups and point-in-time recovery enabled** (the specific plan tier is a cost decision for the business, not an engineering one — the requirement is "backups exist," any paid tier satisfies it). Staging stays on a low/free tier deliberately: it is disposable and reseedable, and paying for backup infrastructure on a database nothing depends on long-term would itself be an unnecessary service.

## Storage

No change from today: uploaded document bytes remain a Postgres column. Documented here as a deliberate decision, not an oversight — see [01](01_INFRASTRUCTURE_ASSESSMENT.md).

## Networking

Unchanged topology in both new and existing environments: OPA embedded in the same container as the API, reachable only via loopback, never a separate network-addressable service. This keeps staging's threat model identical to production's, which matters for staging to be a meaningful rehearsal environment.

## DNS and TLS

Production keeps its existing custom domain(s). Staging gets one new subdomain per surface (e.g. `staging-api.<domain>`, `staging.<domain>`), provisioned the same way the production domains already were. TLS is unchanged in mechanism — both Render and Vercel issue and renew certificates automatically for any domain attached to them; the only new work is attaching the two staging domains, not building any new TLS machinery.

## Backups and disaster recovery

Full detail in [06_BACKUP_DISASTER_RECOVERY_PLAN.md](06_BACKUP_DISASTER_RECOVERY_PLAN.md). Summary: production's paid-tier Postgres backups (daily + PITR) are the entire backup strategy — no separate, custom backup script is being built, because Render's own managed feature already does this once the plan is upgraded, and building a redundant custom mechanism on top would be an unnecessary service.

## Deployment flow

1. A pull request opens against `main` → existing CI (`server-tests`, `server-image`, `frontend-build`) runs, unchanged.
2. On merge to `main` → **new**: an automated deploy to **staging** (Render + Vercel APIs, scripted, not manual).
3. The existing `scripts/smoke_test.py` runs against staging automatically after that deploy.
4. A **deliberate, manually-triggered** promotion step deploys the same, already-tested artifact to **production** — never automatic, so a human decision always gates what real customers see.

This is the same shape already scoped as Q-H2a/b/c in the prior sprint's [`04_BUILD_ROADMAP.md`](../04_BUILD_ROADMAP.md) — Sprint 1 is where it's actually specified and built, not a new decision.

## Scaling strategy

**Vertical first.** At current traffic, upgrading a Render plan tier (more CPU/memory to the single instance) solves any real capacity problem long before horizontal scaling is justified. **One real blocker to horizontal scaling, named now so it isn't rediscovered later under pressure**: the current rate limiter (`server/app/security.py`) is in-process, per-instance memory — running two API instances behind a load balancer today would make it silently under-count and over-allow requests, not fail safe. This must be moved to a shared store (Redis, or Render's own equivalent) *before* any horizontal scaling, not after. No other component in the runtime path (the Decision Engine, OPA, Evidence signing) has a stateful, single-instance assumption — confirmed directly against [`SPECIFICATION/45_PHASE_5_BROKEN_PROMISE_REPORT.md`](../../SPECIFICATION/45_PHASE_5_BROKEN_PROMISE_REPORT.md)'s own architecture findings, which is exactly why this blueprint doesn't need to touch the runtime layer at all to plan for scale.
