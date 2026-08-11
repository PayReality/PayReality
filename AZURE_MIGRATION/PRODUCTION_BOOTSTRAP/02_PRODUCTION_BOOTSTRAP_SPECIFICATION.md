# Production Bootstrap Program — Phase 2: Production Bootstrap Specification

**Method:** inspected `server/app/main.py`'s startup sequence and every service it calls, plus the Terraform variables that feed them. Every item below is either (a) code that already exists and runs automatically, and therefore needs no new building, or (b) a real, specific value that must be supplied before that code can run correctly. Nothing below is invented — each item traces to a specific line of existing code or Terraform variable.

## What already exists in code and requires no new work

`main.py`'s `lifespan` context runs three idempotent, run-every-boot hooks, in order:

1. **`_register_current_signing_key()`** → `signing_key_service.ensure_current_key_registered(db, key_id, public_key)`. Derives the public key from `EVIDENCE_SIGNING_KEY_B64` and registers it under `EVIDENCE_SIGNING_KEY_ID` if not already present. **This is "register production signing key" and "initialize runtime signing-key registry" from the Phase 2 examples — already built, already tested (Milestone 5, staging).**
2. **`_bootstrap_organisation_owner()`** → `organization_service.ensure_owner_bootstrapped(db)`. Creates exactly one `Organization` (named `settings.organization_name`) and exactly one `User` with role `OWNER` (email `settings.owner_email`, an unrecoverable random password) if neither exists yet. **This is "initial administrator" and "initial organization" from the Phase 2 examples — already built, already tested (every milestone from 3 onward has observed `organisation_bootstrapped` / `organisation_owner_bootstrapped` in real startup logs).**
3. **`_reconcile_opa_with_active_policies()`** → loads whatever runtime policies exist in the database into OPA. With zero policies (see below), this correctly reconciles to an empty bundle — not an error state, the correct state for a system with no policies yet.

**None of these need to be written. They need real secrets and correct Terraform variables to run against, which is the rest of this specification.**

## What must be supplied — secrets

| Secret | Source | Status for a new prod environment |
|---|---|---|
| `database-url` | Terraform-generated (`modules/postgres`, `random_password` + connection string assembly) | Automatic on `terraform apply` — no manual step |
| `postgres-administrator-password` | Terraform-generated | Automatic |
| `evidence-signing-key-b64` / `evidence-signing-key-id` | Must be freshly generated for this environment, same method as Milestone 5's staging fix (`nacl.signing.SigningKey.generate()`), installed via `az keyvault secret set`, then a **new Container App revision** (not just a restart — confirmed unreliable in Milestone 5 testing) | **Not yet done for prod — prod doesn't exist yet** |
| `admin-api-key` | Freshly generated (`secrets.token_urlsafe(32)` or equivalent), same method as Milestone 5 | **Not yet done for prod** |
| `anthropic-api-key` | Real third-party credential — this program cannot generate it | **Still blocked, independent of everything else in this program** |

**A key naming decision, stated explicitly rather than assumed:** should the production signing key reuse the identifier pattern `signing_key_azure_prod_v1` from staging, or should it get a distinct `key_id` (e.g. `signing_key_prod_v1`, matching Render's own naming convention for its production key, `render.yaml`)? Since the signing-key registry supports multiple coexisting keys by `key_id` and this is now the *only* production key (no Render-issued Evidence needs to verify against it), this specification recommends `signing_key_prod_v1` — the same convention Render's own `render.yaml` already used for its production key, since Azure is now assuming that exact role, not a new one Render's naming never anticipated. This is a naming choice for whoever executes Phase 4, not a default this document invents on its own authority.

## What must be supplied — Terraform variables (`environments/prod.tfvars`)

Already set, verified present and structurally complete: `environment`, `owner`, `cost_center`, `github_repository`, `postgres_geo_redundant_backup_enabled`, `storage_replication_type`, `container_apps_min_replicas`, `alert_notification_email`.

**Not yet set, using defaults that need a decision before apply:**
- `container_image` — defaults to the Milestone 2 placeholder (`mcr.microsoft.com/k8se/quickstart`). Must be updated to a real, built image tag as part of Phase 4 deployment initialization — the exact same pattern Milestone 3 followed for staging (build via `az acr build`, tag with the commit SHA, update the tfvars).
- `organization_name` — not overridden anywhere; defaults to `"PayReality"`. This is very likely correct and requires no change, but is named here so it's a conscious non-decision, not an unnoticed one.
- **`owner_email`** — this is not actually a variable of its own; `main.tf` wires `owner_email = var.owner` directly, so whatever email is in `prod.tfvars`'s `owner` field (`payreality.ceo@gmail.com`) becomes the literal email of the real, first, bootstrapped production Organisation Owner the moment this environment boots. **This is a real decision being made implicitly by a tagging-convention value, and this specification flags it rather than assumes it's correct.** Confirm this is genuinely the intended first production admin identity before proceeding — if not, `prod.tfvars`'s `owner` value needs to change, which also changes resource tagging (a smaller, likely acceptable side effect, but a real one).

## What is deliberately NOT part of this specification

**Policy bootstrap.** The Phase 2 instructions list this as conditional ("if required") and separately instruct "do not invent bootstrap data." With zero production customers and zero existing policies anywhere, there is no real policy to seed, and inventing a placeholder one would be exactly the kind of fabricated bootstrap data this program's rules forbid. The correct, already-working behavior is: OPA reconciles to an empty policy set at boot (confirmed, not a bug), and the first real policy is created by the real Organisation Owner through the product itself, after they claim their account via `/v1/auth/setup-owner` with the real Operator Key. This specification recommends explicitly **not** building any policy-seeding mechanism.

## Deployment-time actions this specification implies (executed in Phase 4, not here)

1. Generate and install the production signing key and admin key.
2. Confirm or correct `owner_email`'s source value.
3. Build and push a real application image to prod's own Container Registry (each environment gets its own, per `locals.tf`'s naming — `acrprstagingXXXX`-style but for prod).
4. Set `container_image` in `prod.tfvars` to that image.
5. Apply Terraform.
6. Let the existing, already-tested startup hooks run — no new code executes here that hasn't already been exercised in staging.
