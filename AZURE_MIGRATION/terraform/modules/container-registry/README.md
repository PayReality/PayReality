# Module: container-registry

**Owner:** platform/infrastructure engineer (provisioning); CI pipeline (image push, once built). **Purpose:** stores the PayReality API's container image — the structural dependency Milestone 1's Discovery found missing from this project's original service list (a registry with no compute service to run the image would leave Milestone 6 nowhere to deploy to; that gap is closed in `modules/container-apps`, not here, but is the reason this module exists at all).

## What this module creates

One Container Registry, **Standard SKU**, `admin_enabled = false`. Two role assignments: `AcrPull` for the Container App's runtime identity, `AcrPush` for the CI/CD identity (`modules/managed-identity`) — never the same identity for both.

## Image naming

`<login_server>/payreality-api:<tag>`. Tag strategy (for a future milestone to implement, not this one): the git commit SHA that produced the image, so any deployed revision is traceable to an exact commit — never `:latest` in any environment beyond a developer's own local pull.

## Retention

**Not configured in this module.** Azure Container Registry's automatic untagged-manifest retention policy is a Premium-SKU feature; this project uses Standard (see "Why Standard, not Premium" below). Image cleanup is a documented future concern (`docs/FUTURE_EXPANSION.md`), not a gap silently left open — at this project's current deploy frequency, registry storage cost from retained old images is negligible.

## Authentication

Azure AD only, via the two managed identities' RBAC role assignments above. The registry's built-in admin username/password is disabled entirely (`admin_enabled = false`) — there is no static, long-lived registry credential anywhere in this project for anything to leak.

## CI integration

**Implemented** (`.github/workflows/azure-backend-deploy.yml`, added 2026-08-19): the CI/CD identity (`modules/managed-identity`) is federated to GitHub Actions' OIDC issuer, scoped to one repository and one branch, and the workflow uses `azure/login` with this identity's `client_id` (no secret), then `az acr build` to build and push in one step. Two role assignments were needed beyond the identity's Terraform-provisioned `AcrPush` (which alone doesn't cover `az acr build`'s ARM/management-plane build-queuing call): `Contributor` on this registry, and `Container Apps Contributor` on the prod Container App -- both added directly via the Azure REST API, each scoped to exactly one resource, not yet reflected in this Terraform module pending a fix to how prod/staging state is separated in this project (see `BACKLOG_V1_CLOSURE.md`).

## Image promotion strategy

Not built this milestone. The intended shape, for when CI/CD is actually implemented: the same image, built once, is promoted from staging to production by retagging (not rebuilding) — consistent with Sprint 1's Infrastructure Blueprint's deployment flow (build once, deploy the identical artifact to staging, then promote the same artifact to production on manual approval).

## Why Standard, not Premium

Premium's additional capabilities (geo-replication, Private Endpoints, content-trust, retention policies) have no current requirement behind them at this project's scale — one region, one Container App, one image. Provisioning Premium now, for capabilities nothing yet needs, is exactly the unnecessary technology this milestone's Absolute Rules forbid. Named as a real, understood upgrade path if a second region or a compliance requirement for registry-level Private Endpoints ever materializes.
