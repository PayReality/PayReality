# Module: container-apps

**Owner:** platform/infrastructure engineer (provisioning); on-call engineer (runtime). **Purpose:** the Azure replacement for Render's `payreality-api` web service — the compute target Milestone 1's Discovery found missing from the original service list.

## Environment

One `azurerm_container_app_environment`, VNet-integrated into the delegated `container-apps` subnet (`modules/networking`), wired to Log Analytics (`modules/monitoring`) from the moment it exists — not added later in Milestone 8.

## Container

One container, running the exact image `entrypoint.sh` already builds today (`server/Dockerfile`, confirmed in `AZURE_MIGRATION/MILESTONE_1_DISCOVERY.md`) — this module does not change what runs inside the container, only where it runs. `cpu = 0.5`, `memory = 1Gi` by default, sized to today's pilot-scale traffic, both variables rather than hardcoded.

## Environment variables and Managed Identity integration

Every plain (non-secret) variable is set as a literal `env` block, classified exactly per Sprint 1's `PRODUCT_ROADMAP/SPRINT_1/03_ENVIRONMENT_STANDARD.md`. Every secret (`DATABASE_URL`, `EVIDENCE_SIGNING_KEY_B64`, `EVIDENCE_SIGNING_KEY_ID`, `ADMIN_API_KEY`, `ANTHROPIC_API_KEY`) is a Key-Vault-backed `secret` block, resolved by the Container App platform using the runtime managed identity **before the container starts** — the application reads an ordinary environment variable either way. **`server/app/config.py` requires no code change**: it already reads these exact names from the process environment today.

`OPA_URL` and `OPA_BINARY_PATH` are deliberately absent from this list — the first because `config.py`'s own default (`http://localhost:8181`) is already correct for the embedded-OPA topology this module preserves unchanged (see "Scaling," below), the second because Sprint 1's own audit found it dead configuration read by no code path.

## Scaling

`min_replicas = 1` (always warm — no cold-start latency for a production API), `max_replicas = 3`, one `http_scale_rule` on concurrent request count. **A named, deliberate limit, not an oversight**: raising `max_replicas` beyond what's set here without first fixing the in-process rate limiter (`server/app/security.py`, flagged in `AZURE_MIGRATION/MILESTONE_1_DISCOVERY.md`'s risk notes and already tracked as Sprint 1's deferred Task T12) would silently under-count rate limits the moment more than one replica actually runs. This module does not fix that — it names the constraint so `max_replicas` is never raised past it by someone who hasn't read this far.

## Revision strategy

`revision_mode = "Single"` — one active revision at a time, no traffic-splitting between old and new. Container Apps' multi-revision, weighted-traffic-split capability is real and available later if a genuine blue-green deployment need arises; provisioning that abstraction now, with nothing yet to split traffic between, would be exactly the unnecessary complexity this milestone's Absolute Rules forbid. Rollback today means redeploying the previous image tag, not shifting a traffic-weight percentage — adequate for this project's current deploy frequency.

## Health probes

Liveness → `/health`, readiness → `/health/ready` — the exact two endpoints the application already exposes, confirmed directly in Milestone 1's Discovery. Zero application change required for either.

## Ingress

External, HTTPS-only, Container Apps' own managed certificate on the default `*.azurecontainerapps.io` domain. **No custom domain is bound in this milestone** — `api.aisecurewatch.com` continues pointing at Render until Milestone 9's DNS cutover; binding it here, now, would let Azure silently start receiving production traffic before this program's own verification gates are satisfied.

## Future horizontal scaling

Named, not built: (1) the rate-limiter fix noted above under Scaling; (2) Container Apps workload profiles, if `max_replicas`'s consumption-plan ceiling is ever actually reached — the container-apps subnet is already sized `/23` (`modules/networking`) specifically so this doesn't require re-addressing later.

## Inputs / Outputs

See `variables.tf`/`outputs.tf`. Every secret-related input is a Key Vault Secret *resource ID*, never a value.
