# Azure Production Migration Program — Milestone 2: Verification Report

**Status:** final. Every check below was actually run this session, not asserted.

## Terraform formatting

```
terraform fmt -recursive -check
```
Run against `AZURE_MIGRATION/terraform/` and `AZURE_MIGRATION/bootstrap/` separately. **Result: clean, exit 0, both directories.** (One real formatting pass was required and applied before this — see the Migration Report's "Errors found and fixed" section.)

## Terraform validation

```
terraform init -backend=false   # no backend, no Azure credentials needed — providers only
terraform validate
```
Run against both directories. **Result: `Success! The configuration is valid.`, both directories.** This required one real fix first (see Migration Report) — the `azurerm_storage_container` resource's `storage_account_id` argument does not exist in the pinned provider version (`~> 3.117`); the correct argument at that version is `storage_account_name`. Caught by validate, not assumed.

## Module dependency correctness

Confirmed by `terraform init`/`validate` succeeding at all — Terraform statically resolves every module's `source` and every cross-module variable reference as part of both commands; a missing or mismatched output/input would have failed init or validate, not passed silently. Manually re-traced the dependency chain in `docs/MIGRATION_DEPENDENCIES.md`'s "Module apply order" section as a second, human-readable check.

## Output consistency

Every module's `outputs.tf` output that a downstream module or the root `outputs.tf` needs is referenced by exact name (confirmed by `terraform validate` — a wrong output name is a validation error, not a silent `null`). Checked directly: `module.postgres.connection_string_secret_id` (renamed mid-build from an earlier `connection_string_secret_name` — see Migration Report) is referenced correctly in both `main.tf` and nowhere still refers to the old name (confirmed via a repository-wide search for the old name returning zero results).

## Variable consistency / no unused variables

Every variable declared in every module's `variables.tf`, and every root-level variable in `terraform/variables.tf`, is referenced at least once — checked directly with a per-module grep comparing declared names against their usage in that module's `main.tf` (and the root's `main.tf`/`locals.tf` for root variables). Zero unused variables found across all eleven `variables.tf` files (ten modules plus root).

## No circular dependencies

The module graph is a strict DAG: `resource-group` → `networking`/`managed-identity` → (`key-vault`, `postgres`, `storage`, `container-registry`, `monitoring`, each independent of the others) → `container-apps` → `diagnostics`. No module's `main.tf` references anything from a module later in this chain. `terraform validate`'s success is itself confirmation — Terraform's module-reference resolution would fail on a genuine cycle, not silently accept one.

## No duplicated resources

Checked directly: every `resource "type" "name"` declaration across the entire project (`terraform/` and `bootstrap/` combined) is unique — confirmed by extracting every declaration and counting occurrences; every count was exactly 1.

## Application test suite

```
pytest -q   (server/, using the existing .venv)
```
**Result: 194 passed, 0 failed, 0 skipped** — identical to the count before this milestone began. Confirms directly, not by inference from "no application file was touched," that this milestone had zero behavioral effect on the running system.

## Repository safety

`git status` confirms every change in this milestone is contained under `AZURE_MIGRATION/` — zero files under `server/`, `SPECIFICATION/`, or `PRODUCT_ROADMAP/` were modified, added, or deleted.
