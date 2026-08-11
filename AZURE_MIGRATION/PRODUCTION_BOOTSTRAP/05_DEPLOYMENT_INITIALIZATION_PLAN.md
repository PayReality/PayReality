# Production Bootstrap Program — Phase 4: Deployment Initialization Plan

**Status: plan only. Nothing in this document has been executed.** Every step is written to be repeatable (running it again against an already-initialized environment should be a safe no-op or a clean update, never a duplicate/corrupt state) and idempotent, consistent with the existing Terraform modules' own design (already proven idempotent across Milestones 3–5's many re-applies) and the application's own startup hooks (already proven idempotent — `ensure_owner_bootstrapped` and `ensure_current_key_registered` both explicitly no-op if their target already exists).

## Step 1 — Resolve open decisions

Confirm `owner_email`'s source value, the signing key's `key_id`, and the custom-domain-vs-default-hostname choice (`04_PRODUCTION_ENVIRONMENT_GAP_ANALYSIS.md`). **Idempotent by nature** — a decision, once made, doesn't need remaking on a re-run.

## Step 2 — Provision Azure infrastructure

```
cd AZURE_MIGRATION/terraform
terraform init -backend-config="key=payreality-prod.tfstate" [... other backend-config flags, per versions.tf's documented pattern]
terraform plan -var-file=environments/prod.tfvars -out=prod.tfplan
# review in full
terraform apply prod.tfplan
```
**Idempotent**: Terraform's own core guarantee — re-running `plan` after a successful `apply` shows "No changes," exactly as staging has repeatedly demonstrated. **Repeatable**: this is the same command shape used for staging in Milestones 3–5.

## Step 3 — Initialize secrets

```
az keyvault secret set --vault-name <prod-vault-name> --name evidence-signing-key-b64 --value "<freshly generated>"
az keyvault secret set --vault-name <prod-vault-name> --name evidence-signing-key-id --value "<decided key_id>"
az keyvault secret set --vault-name <prod-vault-name> --name admin-api-key --value "<freshly generated>"
```
`database-url` and `postgres-administrator-password` need no manual action — Terraform generated them in Step 2. **Idempotent**: `az keyvault secret set` on an unchanged value creates a new version with the same content — harmless to re-run. **Not yet idempotent against the running Container App** — see Step 5.

## Step 4 — Build and push the application image

```
az acr build --registry <prod-registry-name> --image payreality-api:prod-<commit-sha> server/
```
Update `container_image` in `prod.tfvars` to this tag, then re-run Step 2's `plan`/`apply` (a second, small, reviewed apply — not a new mechanism). **Idempotent**: re-running the identical `az acr build` command produces the identical image content for the same commit; the tag itself is immutable once pushed (established practice since Milestone 3).

## Step 5 — Force a new Container App revision to pick up secrets

```
az containerapp revision copy --name <prod-container-app-name> --resource-group <prod-rg> --revision-suffix init01
```
**Required, not optional** — Milestone 5 confirmed a plain `revision restart` on the same revision is unreliable for picking up newly-set Key Vault values, even with versionless references (which this environment's Terraform modules already use — no change needed there). A genuinely new revision is the confirmed-reliable method.

## Step 6 — Verify the automatic bootstrap hooks ran correctly

Query Log Analytics for the first boot's startup sequence (same method used throughout Milestones 3–5):
```
az monitor log-analytics query --workspace <prod-workspace-id> --analytics-query \
  "ContainerAppConsoleLogs_CL | where Log_s has 'bootstrapped' or Log_s has 'signing_key' | order by TimeGenerated asc"
```
Confirm `organisation_bootstrapped`, `organisation_owner_bootstrapped`, and `signing_key_registered` all appear, with no `_failed_at_startup` line after them. **This step only observes** — it does not perform bootstrap, since Step 2/5 already caused the application to do that itself, automatically, via existing code.

## Step 7 — Validate health

```
curl https://<prod-container-app-default-hostname>/health
curl https://<prod-container-app-default-hostname>/health/ready
```
Both must return `200`; `/health/ready` must show `database: true, opa: true`.

## Step 8 — Smoke test

Claim the Owner account via `POST /v1/auth/setup-owner` using the real Operator Key from Step 3, using a real password. Confirm login succeeds. This is the first genuinely manual, human action in this entire sequence — everything before it is either Terraform or a documented `az` command.

## Repeatability statement

Steps 2–7 can be re-run in full against a from-scratch subscription (a full disaster-recovery rebuild scenario) and should produce an identical result, by design — this is the same property Milestone 2's own "reproducible from an empty Azure subscription" rule already required of every module used here, re-confirmed applicable to a fresh prod environment specifically, not just staging.
