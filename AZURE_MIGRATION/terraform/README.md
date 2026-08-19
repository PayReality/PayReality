# Terraform: prod/staging state separation

**Always run `./init-env.sh <prod|staging>` before any `plan`/`apply` in this directory. Never a bare `terraform init`.**

## Why this exists

On 2026-08-19, a bare `terraform init` in this directory silently reused a local backend cache left over from a previous session, one pointed at prod's state (`payreality-prod.tfstate`). Running `terraform plan -var-file=environments/staging.tfvars` against it produced a plan to destroy and recreate 61 real resources, since Terraform was comparing staging's intended configuration against prod's actual state. Nothing was applied that time, but the mechanism is real and easy to repeat by accident: `terraform init` with no backend-config flags at all is valid and succeeds silently, it just keeps whatever was cached.

`init-env.sh` always passes `-reconfigure` with an explicit `key=payreality-<env>.tfstate`, so every invocation is a fresh, unambiguous statement of which environment's state you're about to touch. There is no bare `terraform init` path left that this workflow depends on.

## The safe sequence, every time

```sh
./init-env.sh staging
terraform plan  -var-file=environments/staging.tfvars
terraform apply -var-file=environments/staging.tfvars   # only if the plan is what you expect
```

Swap `staging` for `prod` for the other environment. Always re-run `init-env.sh` when switching between them in the same session, never assume the cache still matches.

## `container_image` and the backend CD pipeline

Since `.github/workflows/azure-backend-deploy.yml` (added 2026-08-19), prod's actual running image is updated directly by every push to `main`, bypassing Terraform. `environments/prod.tfvars`'s `container_image` is kept in sync manually so `plan` doesn't report false drift; if it ever falls behind a real CD deploy, the resulting plan is a one-field `container_image` change and nothing else, safe either to apply (harmless: it just re-asserts whatever CD already deployed) or to fix by updating the tfvars line to match. Staging has no CD pipeline yet, so its `container_image` is still Terraform's alone to manage.
