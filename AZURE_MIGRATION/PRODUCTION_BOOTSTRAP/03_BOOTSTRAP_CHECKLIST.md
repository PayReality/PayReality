# Production Bootstrap Program — Phase 2: Bootstrap Checklist

Execution-tracking form of `02_PRODUCTION_BOOTSTRAP_SPECIFICATION.md`. Nothing on this checklist has been executed — this is the checklist to be used during Phase 4, not a report of completed work.

## Decisions to make before any action

- [ ] Confirm `payreality.ceo@gmail.com` (currently `prod.tfvars`'s `owner` value, inherited from resource-tagging convention) is genuinely intended as the first production Organisation Owner's login email. If not, change `owner` in `prod.tfvars` before applying.
- [ ] Confirm the production signing key's `key_id` — this checklist recommends `signing_key_prod_v1` (matching Render's own retired convention), but this is a naming decision, not a default to accept silently.
- [ ] Confirm no policy-seeding mechanism should be built (recommendation: correct — zero policies is the right starting state; the real Owner creates the first real policy through the product after claiming their account).

## Secrets

- [ ] Generate a fresh Ed25519 signing key (`nacl.signing.SigningKey.generate()`), same method as Milestone 5.
- [ ] Generate a fresh Admin API key (`secrets.token_urlsafe(32)` or equivalent).
- [ ] Obtain the real `ANTHROPIC_API_KEY` from whoever owns that account relationship — independent of everything else, and not blocking core platform bootstrap.

## Terraform

- [ ] Build and push a real application image to prod's own Container Registry.
- [ ] Set `container_image` in `prod.tfvars` to that real tag.
- [ ] Resolve the `owner`/`owner_email` decision above.
- [ ] `terraform plan -var-file=environments/prod.tfvars` against a real `payreality-prod.tfstate` backend key, reviewed in full before any apply.

## Post-apply, automatic (no manual action — verify, don't perform)

- [ ] Confirm `organisation_bootstrapped name=PayReality` appears in the first boot's logs.
- [ ] Confirm `organisation_owner_bootstrapped email=<the confirmed owner_email>` appears.
- [ ] Confirm `signing_key_registered key_id=<the confirmed key_id>` appears, with no preceding `signing_key_registration_failed_at_startup`.
- [ ] Confirm the public key exposed at `/v1/evidence/verification-keys` matches an independently-computed value from the installed private key (the same validation method used in Milestone 5).

## What this checklist deliberately excludes

Any data-import, data-validation, or migration-rollback item — none apply, per `01_REVISED_PRODUCTION_READINESS_REPORT.md`'s finding that there is no production data to migrate.
